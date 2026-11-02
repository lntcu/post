"""Local pixel-based pen-grip classification with CLIP and rated image examples.

CLIP's relative text matches are not calibrated correctness probabilities. A
quality rating is predicted only from explicitly rated image examples; grip type
never supplies an assumed good/bad score. Images are not persisted.
"""
from collections import defaultdict
from io import BytesIO
import json
import math
from pathlib import Path
import secrets
import threading
import time

import numpy as np

from prepare_grip_model import MODEL_DIR, MODEL_ID, REVISION

GRIPS = {
    'tripod': ('Tripod', 'a pen held between the thumb and index finger and resting on the middle finger'),
    'quadrupod': ('Quadrupod', 'a pen held with the thumb, index and middle fingers and resting on the ring finger'),
    'lateral_tripod': ('Lateral tripod', 'a pencil held with the thumb crossing over the index finger and supported by the middle finger'),
    'lateral_quadrupod': ('Lateral quadrupod', 'a pencil held with the thumb crossing the index finger and supported by the ring finger'),
    'thumb_wrap': ('Thumb wrap', 'a pen held with the thumb wrapped around the fingers'),
    'fisted': ('Fisted', 'a pencil grasped inside a closed fist'),
    'other': ('Other or adapted grip', 'a hand holding a pen in an unusual or adapted writing grip'),
}
PRESENCE = (
    ('holding_pen', 'a close-up photo of a hand holding a pen or pencil to write on paper'),
    ('empty_hand', 'a close-up photo of an empty hand without a pen or pencil'),
    ('pen_on_desk', 'a photo of a pen or pencil lying on a desk without being held'),
    ('other_object', 'a photo of a hand holding an object other than a pen or pencil'),
    ('unclear', 'a blurry photo of a room or desk without a visible writing hand'),
)
LIMITATION = 'Experimental image matches, not validated grip correctness, pressure, or comfort. Grip type alone does not determine writing quality.'


def softmax(values):
    values = np.asarray(values, dtype=np.float64)
    exp = np.exp(values - np.max(values))
    return exp / exp.sum()


def unit_vector(value):
    vector = np.asarray(value, dtype=np.float32)
    if vector.shape != (512,) or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-8:
        raise ValueError('Invalid image embedding.')
    return vector / np.linalg.norm(vector)


def crop_hand(frame, landmarks=None):
    """Use landmarks only to frame pixels; all classification uses image content."""
    height, width = frame.shape[:2]
    if height < 1 or width < 1:
        raise ValueError('Empty camera image.')
    if landmarks is not None and len(landmarks) == 21:
        points = np.array([(p.x * width, p.y * height) for p in landmarks])
        if np.isfinite(points).all():
            low, high = points.min(axis=0), points.max(axis=0)
            side = max(high-low) * 1.9
            if side >= 64:
                center = (low+high)/2
                x0, y0 = np.maximum(0, center-side/2).astype(int)
                x1, y1 = np.minimum([width, height], center+side/2).astype(int)
                if x1-x0 >= 32 and y1-y0 >= 32:
                    return frame[y0:y1, x0:x1].copy(), [int(x0), int(y0), int(x1), int(y1)]
    # Full frame remains assessable when hand landmark tracking fails. The user
    # can put the hand/pen close to the camera or assess an uploaded photo.
    return frame.copy(), [0, 0, width, height]


def decode_photo(encoded):
    import base64
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not isinstance(encoded, str) or len(encoded) > 6_000_000:
        raise ValueError('Choose an image smaller than 4 MB.')
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 16_000_000 or min(source.size) < 32:
                raise ValueError('Choose an image between 32 pixels and 16 megapixels.')
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1024, 1024))
            return image.copy()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError('Could not read this photo. Choose a JPEG, PNG or WebP image.') from exc


class ImageExamples:
    """Persist only human labels, ratings and image embeddings, never photos."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.items = []
        self.error = ''
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if data.get('schema') != 'grip-image-examples-v1' or data.get('model') != MODEL_ID or data.get('revision') != REVISION:
                    raise ValueError('Incompatible examples.')
                for item in data['examples']:
                    self.validate(item['label'], item['rating'])
                    unit_vector(item['embedding'])
                if len(data['examples']) > 500:
                    raise ValueError('Too many examples.')
                self.items = data['examples']
            except (ValueError, OSError, KeyError, TypeError, AttributeError):
                self.error = 'Saved image examples could not be read. Restore the examples file before adding more.'

    @staticmethod
    def validate(label, rating):
        if label not in GRIPS:
            raise ValueError('Choose a supported grip label.')
        if type(rating) not in (int, float) or not math.isfinite(rating) or not 0 <= rating <= 100:
            raise ValueError('Example rating must be between 0 and 100.')

    def add(self, embedding, label, rating):
        self.validate(label, rating)
        vector = unit_vector(embedding)
        with self.lock:
            if self.error:
                raise ValueError(self.error)
            if len(self.items) >= 500:
                raise ValueError('The image library already contains 500 examples.')
            if any(float(np.dot(vector, unit_vector(x['embedding']))) > .99999 for x in self.items):
                raise ValueError('This image is already in the example library. Add a different view or writing pose.')
            item = {'id': secrets.token_hex(8), 'label': label, 'rating': float(rating), 'embedding': vector.tolist()}
            updated = [*self.items, item]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'schema': 'grip-image-examples-v1', 'model': MODEL_ID,
                                             'revision': REVISION, 'examples': updated}, allow_nan=False))
            temporary.replace(self.path)
            self.items = updated
            return item['id']

    def status(self):
        with self.lock:
            return {'count': len(self.items), 'labels': sorted({item['label'] for item in self.items}), 'error': self.error}

    def predict(self, embedding):
        with self.lock:
            items = list(self.items)
        if not items:
            return None
        vector = unit_vector(embedding)
        similarities = np.array([np.dot(vector, unit_vector(item['embedding'])) for item in items])
        # Average the best matches per class to avoid voting by sample count.
        groups = defaultdict(list)
        for index, item in enumerate(items):
            groups[item['label']].append(index)
        class_similarity = {label: float(np.mean(sorted(similarities[indices], reverse=True)[:3])) for label, indices in groups.items()}
        label = max(class_similarity, key=class_similarity.get)
        nearest = np.argsort(similarities)[::-1][:5]
        weights = softmax(similarities[nearest]*30)
        # One rating cannot define a scale; retain recognition scoring until there
        # are contrasting rated examples. Never attach fixed scores to grip types.
        has_scale = len({item['rating'] for item in items}) >= 2
        rating = float(sum(w * items[i]['rating'] for w, i in zip(weights, nearest))) if has_scale else None
        return {'label': label, 'rating': round(rating) if rating is not None else None,
                'similarity': round(float(similarities[nearest[0]]), 4), 'examples': len(items),
                'neighbors': [{'id': items[i]['id'], 'label': items[i]['label'], 'rating': items[i]['rating'],
                               'similarity': round(float(similarities[i]), 4)} for i in nearest]}


class GripImageModel:
    def __init__(self, model_dir=MODEL_DIR):
        self.model_dir = Path(model_dir)
        self.lock = threading.Lock()
        self.model = None

    def load(self):
        if self.model is not None:
            return
        import torch
        from transformers import CLIPModel, CLIPProcessor
        if not (self.model_dir / 'model.safetensors').is_file():
            raise RuntimeError('Image model is not installed. Run: python prepare_grip_model.py')
        torch.set_num_threads(2)
        self.torch = torch
        self.processor = CLIPProcessor.from_pretrained(str(self.model_dir), local_files_only=True, use_fast=False)
        model = CLIPModel.from_pretrained(str(self.model_dir), local_files_only=True, use_safetensors=True).eval()
        prompts = [prompt for _, prompt in PRESENCE]
        prompts += [f'A close-up photograph of {description}.' for _, description in GRIPS.values()]
        inputs = self.processor(text=prompts, padding=True, return_tensors='pt')
        with torch.inference_mode():
            features = model.get_text_features(**inputs)
            features = features / features.norm(dim=-1, keepdim=True)
        self.text_features = features.numpy()
        self.scale = float(model.logit_scale.exp().detach())
        self.model = model

    def analyze(self, image, examples):
        with self.lock:
            self.load()
            inputs = self.processor(images=image, return_tensors='pt')
            with self.torch.inference_mode():
                embedding = self.model.get_image_features(**inputs)[0].numpy()
            embedding = unit_vector(embedding)
            similarities = self.text_features @ embedding
            presence = softmax(similarities[:len(PRESENCE)]*self.scale)
            grip = softmax(similarities[len(PRESENCE):]*self.scale)
        presence_index = int(np.argmax(presence))
        pen_present = presence_index == 0
        label_index = int(np.argmax(grip))
        label = list(GRIPS)[label_index]
        matched = examples.predict(embedding) if pen_present else None
        source = 'zero_shot'
        # Reference examples personalize classification only after a minimum
        # visual match; arbitrary unrelated examples do not override predictions.
        if matched and matched['similarity'] >= .5:
            label, source = matched['label'], 'rated_images'
        rating = matched['rating'] if source == 'rated_images' else None
        score = rating if rating is not None else round(float(presence[0])*100) if pen_present else None
        score_kind = 'example_rating' if rating is not None else 'recognition_match'
        result = {'phase': 'ready', 'model': MODEL_ID, 'method': source, 'pen_present': pen_present,
                  'label': label if pen_present else PRESENCE[presence_index][0],
                  'label_text': GRIPS[label][0] if pen_present else 'Pen holding not recognized',
                  'score': score, 'score_kind': score_kind,
                  'score_label': 'Example-based rating' if rating is not None else 'Pen-holding image match',
                  'label_match': round(float(grip[label_index])*100) if source == 'zero_shot' else None,
                  'presence_matches': {key: round(float(p)*100, 1) for (key, _), p in zip(PRESENCE, presence)},
                  'class_matches_kind': 'relative_text_match',
                  'class_matches': sorted([{'label': key, 'name': name, 'match': round(float(p)*100, 1)}
                    for (key, (name, _)), p in zip(GRIPS.items(), grip)], key=lambda x: x['match'], reverse=True),
                  'example_match': matched, 'limitation': LIMITATION,
                  'guidance': 'Compare the visible grip with examples. Comfort and control need a separate check.' if pen_present else 'Show a close, clear view of the hand holding the pen, or choose a pen-holding photo.'}
        return result, embedding


class GripImageService:
    """One latest-frame slot; slow model inference never blocks camera capture."""
    def __init__(self, examples_path, stop, model=None):
        self.model = model or GripImageModel()
        self.examples = ImageExamples(examples_path)
        self.stop = stop
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.pending = None
        self.result = {}
        self.latest_embedding = None
        self.latest_photo_embedding = None
        self.photo_result = {}
        self.last_submit = -math.inf
        self.active_identity = None
        self.generation = 0
        self.started = False
        self.thread = None

    def start(self):
        with self.lock:
            if not self.started:
                self.started = True
                self.thread = threading.Thread(target=self.run, daemon=True)
                self.thread.start()

    def submit(self, frame, landmarks, identity, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if identity == self.active_identity and now - self.last_submit < 1.:
                return
            pixels, box = crop_hand(frame, landmarks)
            self.active_identity = identity
            self.pending = (pixels, box, identity, now, self.generation)
            self.last_submit = now
            self.wake.set()
        self.start()

    def reset(self):
        with self.lock:
            self.generation += 1
            self.active_identity = None
            self.pending = None
            self.result = {}
            self.latest_embedding = None
            self.last_submit = -math.inf

    def snapshot(self, identity, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.active_identity != identity:
                return {'phase': 'waiting', 'score': None, 'status': 'Waiting for a writing image'}
            if not self.result:
                return {'phase': 'loading', 'score': None, 'status': 'Loading the local image model…'}
            result = dict(self.result)
            if result.get('phase') == 'ready' and now - result['captured_at'] > 5:
                return {'phase': 'waiting', 'score': None, 'status': 'Waiting for a fresh writing image'}
            return result

    def run(self):
        from PIL import Image
        while not self.stop.is_set():
            self.wake.wait(.25)
            with self.lock:
                task = self.pending
                self.pending = None
                self.wake.clear()
            if task is None:
                continue
            pixels, box, identity, captured, generation = task
            try:
                result, embedding = self.model.analyze(Image.fromarray(pixels[:, :, ::-1]), self.examples)
                result.update(captured_at=captured, crop=box)
            except Exception as exc:
                message = str(exc) if isinstance(exc, (ImportError, RuntimeError)) else type(exc).__name__
                result = {'phase': 'error', 'score': None, 'status': f'Image assessment unavailable: {message}'}
                embedding = None
            with self.lock:
                if identity == self.active_identity and generation == self.generation:
                    self.result = result
                    self.latest_embedding = (embedding, captured, identity) if embedding is not None else None

    def photo_snapshot(self):
        with self.lock:
            return dict(self.photo_result)

    def analyze_photo(self, image):
        result, embedding = self.model.analyze(image, self.examples)
        with self.lock:
            self.photo_result = result
            self.latest_photo_embedding = embedding if result['pen_present'] else None
        return result

    def add_example(self, label, rating, source, identity):
        with self.lock:
            if source == 'photo':
                embedding = self.latest_photo_embedding
            elif source == 'camera':
                saved = self.latest_embedding
                embedding = saved[0] if saved and saved[2] == identity and time.monotonic() - saved[1] <= 5 and self.result.get('pen_present') else None
            else:
                raise ValueError('Choose camera or photo as the example source.')
            if embedding is None:
                raise ValueError('Assess a current pen-holding image before saving an example.')
        return self.examples.add(embedding, label, rating)
