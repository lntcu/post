'use strict';
// Display language is a browser preference: it does not change camera or session settings.
(() => {
  const key = 'still-language';
  const zh = {
    'Live monitor':'实时监测','Dashboard':'数据概览','Settings':'设置','Language':'语言','Display language':'显示语言',
    'This choice is saved in this browser.':'此选项会保存在当前浏览器中。','Main navigation':'主导航','Settings categories':'设置分类',
    'Install Still':'安装 Still','AWARENESS, OVER TIME':'持续关注，循序改善','Your day, in perspective.':'看清一天中的变化。',
    'Notice patterns. Make small, comfortable changes.':'发现规律，做出舒适的小调整。','OVERVIEW':'概览',
    'Your workspace. In balance.':'让工作状态更平衡。','A simple view of your session and where to focus.':'查看本次记录及值得关注的变化。',
    'LIVE VIEW':'实时视图','A clearer view.':'更清晰地了解当前状态。','Posture, eye cues, and small adjustments as you work.':'工作时关注姿势、眼部提示与细微调整。',
    'Start session':'开始监测','Pause':'暂停','Resume':'继续','Recalibrate':'重新校准','End session':'结束监测',
    'DEMO · Synthetic measurements and video. This does not test camera accuracy.':'演示 · 使用模拟测量和视频，不代表摄像头检测准确度。',
    'Active reminders':'当前提醒','Session average':'本次平均分','Start a session to see your guidance.':'开始监测后查看建议。',
    'Alignment not assessed':'尚未评估姿势','Average alignment':'平均姿势分','NEXT STEP':'下一步',
    'Start a session when you’re ready.':'准备好后开始监测。','How the score works':'分数如何计算',
    'Colors describe measured changes: green · near reference; blue · suggestion; amber · sustained change; red · sustained change at least twice a measurement threshold. They do not measure medical risk.':'颜色表示测量变化：绿色 · 接近参考姿势；蓝色 · 建议；琥珀色 · 持续变化；红色 · 持续变化达到测量阈值的两倍以上。这些颜色不代表医学风险。',
    'Break check':'休息提示','Waiting for camera':'等待摄像头','Take a 2-min break':'休息 2 分钟',
    'Session analytics':'监测数据','This session':'本次监测','Last 7 days':'最近 7 天','Last 30 days':'最近 30 天',
    'Export CSV ↗':'导出 CSV ↗','ACTIVE TIME':'有效时长','Excludes pauses and unobserved gaps':'不含暂停和未检测时段',
    'NEAR YOUR REFERENCE':'接近参考姿势','Of tracked posture time · not a health score':'占姿势追踪时长 · 并非健康评分',
    'TRACKING COVERAGE':'追踪覆盖率','All configured posture views tracked / active time':'所有已配置视角的追踪时长 / 有效时长',
    'MOVEMENT RESETS':'活动次数','Visible changes that reset stillness':'重置静止计时的可见动作',
    'Posture over time':'姿势变化趋势','Near reference':'接近参考姿势','Changed':'有变化','Untracked':'未追踪',
    'Posture time chart. Detailed values are in the table below.':'姿势时间图，详细数据见下表。','No session data':'暂无监测数据',
    'Charts use sampled time, not frame counts. Missing tracking is never counted as good posture.':'图表按采样时长计算，而非画面帧数。追踪缺失不会计为良好姿势。',
    'View chart values':'查看图表数据','Interval':'时间段','Recurring changes':'反复出现的变化','No data':'暂无数据',
    'An issue’s duration can overlap another issue. These cues describe changes from calibration.':'不同问题的持续时间可能重叠。这些提示表示相对于校准姿势的变化。',
    'Eyes & writing':'眼部与书写','Eyes and writing metrics':'眼部与书写数据','Average estimated blink rate':'平均估计眨眼频率',
    'Writing hand tracked':'书写手追踪时长','Writing cues changed':'书写提示变化时长','Session history':'历史记录',
    'Started':'开始时间','Active time':'有效时长','Coverage':'覆盖率','Movement':'活动','Details':'详情',
    'No saved sessions':'没有保存的监测记录','Live posture and writing monitor':'实时姿势与书写监测',
    'Break':'休息','Break time remaining':'剩余休息时间','remaining':'剩余时间','break complete':'休息完成',
    'End break early':'提前结束休息','Resume session':'继续监测','Posture & hand camera':'姿势与手部摄像头',
    'Camera off':'摄像头已关闭','Live front camera preview':'前置摄像头实时预览','Waiting to start':'等待开始',
    'Tracking coverage will appear here. It describes visible measurements, not certainty about your health.':'追踪覆盖情况会显示在这里。它描述可见测量结果，不代表健康状况。',
    'Hand camera':'手部摄像头','Off':'关闭','Hand camera off':'手部摄像头已关闭','Writing-hand camera preview':'书写手摄像头预览',
    'WRITING HAND':'书写手','Waiting for writing mode':'等待开启书写模式','Show the full writing hand; include your elbow for wrist alignment.':'请让整只书写手和手肘进入画面，以便评估手腕对齐情况。',
    'Hand calibration progress':'手部校准进度','Measurements':'测量数据','Enable writing mode':'开启书写模式',
    'Relearn hand reference':'重新学习手部参考姿势','Reset hand reference':'重置手部参考姿势',
    'Start grip & wrist calibration':'开始握笔和手腕校准','Reset grip & wrist reference':'重置握笔和手腕参考姿势',
    '● Body':'● 身体','● Eyes':'● 眼部','● Hand':'● 手部','Eyes & movement':'眼部与活动',
    'Find your reference':'建立参考姿势','Compare with your starting position.':'与开始时的姿势比较。',
    'Unavailable':'不可用','blinks / min':'次眨眼 / 分钟','current closure':'当前闭眼时长',
    'Stillness':'静止时长','Movement resets this timer.':'活动会重置此计时器。','Side camera':'侧面摄像头',
    'Waiting':'等待中','Live side camera preview':'侧面摄像头实时预览','Waiting for side camera…':'等待侧面摄像头…',
    'Connecting…':'连接中…','Posture measurements':'姿势测量','Measurement':'测量项','Change':'变化','Threshold':'阈值','Guidance':'建议',
    'Complete setup to see your measurements.':'完成设置后查看测量结果。','About measurements':'关于测量',
    'Changes are relative to calibration. ° = degrees; unitless values are ratios of body proportions. Camera proximity uses relative face size, not physical screen distance. Shoulder raise, elbow spread, forward head, and proximity flag increases only. Missing measurements are excluded from scores.':'变化以校准姿势为基准。° 表示角度；无单位数值表示身体比例。摄像头距离使用相对脸部大小，并非真实屏幕距离。肩部抬高、手肘外展、头部前伸和距离变化仅在增加时标记。缺失的测量数据不计入评分。',
    'Hand measurements':'手部测量','Grip & wrist details':'握笔与手腕详情','Interpretation':'说明',
    'Changing the camera angle also changes these measurements. Recalibrate after moving it.':'改变摄像头角度也会影响测量结果，移动后请重新校准。',
    'Grip image model':'握笔图像模型','Start a session to assess the live camera.':'开始监测后可评估实时画面。',
    'Assess a pen-holding photo':'评估握笔照片','Selected grip photo':'选中的握笔照片','Assess photo':'评估照片',
    'Rate an example':'为样本评分','Image source':'图像来源','Assessed photo':'已评估照片','Live camera':'实时摄像头',
    'Grip label':'握笔类型','Tripod':'三指握笔','Quadrupod':'四指握笔','Lateral tripod':'侧向三指握笔',
    'Lateral quadrupod':'侧向四指握笔','Thumb wrap':'拇指包握','Fisted':'拳握','Other / adapted':'其他 / 调整型',
    'Your rating (0–100)':'您的评分（0–100）','Save rated example':'保存评分样本',
    'Photos stay in this browser session; saved examples contain numerical image features and your ratings.':'照片仅保留在当前浏览器会话中；保存的样本只包含数值图像特征和您的评分。',
    'Camera setup':'摄像头设置','Choose camera':'选择摄像头','Show your face and shoulders in even light.':'在均匀光线下露出脸部和肩膀。',
    'Sit comfortably and hold still for 5 seconds.':'舒适坐好并保持静止 5 秒。','Side view: show your ear, nose, and shoulder.':'侧面视角：露出耳朵、鼻子和肩膀。',
    'Ready':'就绪','Start':'开始','Calibration progress':'校准进度','Notifications':'通知','All clear':'暂无提醒',
    'Alerts appear here after your chosen delay.':'提醒会在设定的延迟后显示在这里。','Snooze duration':'暂停提醒时长',
    '5 minutes':'5 分钟','10 minutes':'10 分钟','30 minutes':'30 分钟','Snooze alerts':'暂时关闭提醒','Resume alerts':'恢复提醒',
    'Changes save automatically':'更改会自动保存','Close settings':'关闭设置','Cameras':'摄像头','Reminders':'提醒',
    'Voice':'语音','Hand tracking':'手部追踪','Session & privacy':'监测与隐私','Quiet hours':'免打扰时段',
    'Front camera index':'前置摄像头编号','0 is usually the built-in camera. Try another index if needed.':'0 通常是内置摄像头。如有需要，可尝试其他编号。',
    'Camera view':'摄像头视角','Automatic':'自动','Front · recommended for eyes':'正面 · 适合眼部追踪',
    'Side · forward head position':'侧面 · 适合检测头部前伸','Optional side camera':'可选侧面摄像头',
    'Index (e.g. 1) or direct stream URL':'编号（如 1）或视频流网址',
    'Phone webcam index, MJPEG, or RTSP URL. Each camera calibrates separately.':'可填写手机摄像头编号、MJPEG 或 RTSP 网址。每个摄像头需分别校准。',
    'Reminder preferences':'提醒偏好','Sensitivity':'灵敏度','Gentle · larger changes':'宽松 · 较大变化','Balanced':'平衡',
    'Sensitive · smaller changes':'灵敏 · 较小变化','Posture delay (seconds)':'姿势提醒延迟（秒）',
    'Stillness reminder (minutes)':'静止提醒间隔（分钟）','Notification cooldown (seconds)':'通知冷却时间（秒）',
    'Remind me about':'提醒类别','Posture':'姿势','Eyes':'眼部','Tiredness':'疲劳','Desktop notifications':'桌面通知',
    'Optional · macOS':'可选 · macOS','Off by default. In-app reminders stay on.':'默认关闭。应用内提醒仍会显示。',
    'Requires macOS. In-app reminders stay on.':'需要 macOS。应用内提醒仍会显示。',
    'Voice & spoken reminders':'语音与口头提醒','Speak active warnings':'朗读当前警告','Local voice':'本地语音',
    'System default · local':'系统默认 · 本地','Speaking rate':'语速','Volume':'音量','Enable & test voice':'启用并测试语音',
    'Enable voice once per window. Spoken warnings need this app open and follow snooze, quiet hours, categories, and cooldown.':'每个窗口启用一次语音。语音提醒要求应用保持打开，并遵循暂停、免打扰时段、类别与冷却时间设置。',
    'Enable hand tracking':'开启手部追踪','Writing reminders':'书写提醒','Writing assessment':'书写评估方式',
    'Image model · no markers or calibration':'图像模型 · 无需标记或校准',
    'Geometry comparison · personal reference':'几何比较 · 个人参考姿势','Writing hand':'书写用手',
    'Right hand':'右手','Left hand':'左手','Track blue and green pen markers':'追踪蓝色和绿色笔杆标记',
    'Put a small blue marker near the pen tip and a green marker farther up the shaft, with both visible. Use the same pen and marker positions during calibration and writing. These markers measure the visible shaft, not contact with the page.':'在笔尖附近贴一个小蓝色标记，在笔杆较高位置贴一个绿色标记，并确保两者可见。校准和书写时请使用同一支笔及相同的标记位置。标记仅用于测量可见笔杆，不能判断是否接触纸面。',
    'Optional desk camera':'可选桌面摄像头','Blank uses front camera; or index / stream URL':'留空使用前置摄像头，或填写编号 / 视频流网址',
    'Use a separate, unused camera for an overhead desk view. Keep your wrist and fingers visible.':'俯拍桌面时请使用独立且未被占用的摄像头，并让手腕和手指保持可见。',
    'Compares finger, marked-pen, and wrist measurements with a personal reference. Pressure requires a calibrated sensor; camera proximity does not establish contact.':'将手指、标记笔杆和手腕的测量值与个人参考姿势比较。压力需要经过校准的传感器；摄像头中的接近情况无法证明发生接触。',
    'Use Install Still in the top bar when available, or your browser’s app installation menu, to open a dedicated app window. The local Python server must stay running.':'可使用顶部的“安装 Still”按钮或浏览器的应用安装菜单打开独立窗口。本地 Python 服务器需要持续运行。',
    'Save local session summaries':'保存本地监测摘要',
    'Stores durations, trends, and recurring cues on this computer, up to 200 sessions. No images or landmarks. Changing this starts a new analytics segment. Private intervals are never saved retroactively. Existing history stays until cleared. Demo data is never saved.':'在此电脑上最多保存 200 次监测的时长、趋势和重复提示，不保存图像或关键点。更改此项会开始新的统计区间。隐私时段不会被追溯保存。现有历史记录会保留，直到手动清除。演示数据不会保存。',
    'Export session summaries (CSV)':'导出监测摘要（CSV）','Clear all local history':'清除全部本地历史记录',
    'End the current session before clearing history.':'请先结束当前监测，再清除历史记录。',
    'Suppress dashboard and desktop reminders during these hours, using this computer’s local time. Measurements stay visible.':'根据此电脑的本地时间，在指定时段关闭界面和桌面提醒。测量结果仍会显示。',
    'From':'开始','Until':'结束','Clear quiet hours':'清除免打扰时段',
    'Pause releases the cameras. Resuming starts a fresh calibration. Stop turns off monitoring.':'暂停会释放摄像头。继续时会重新校准。结束会关闭监测。',
    'Preferences saved':'设置已保存','Unsaved changes':'更改尚未保存',
    'Not assessed':'尚未评估','Suggestion':'建议','Correction':'需要调整','Review now':'请立即查看',
    'Limited':'有限','Partial tracking':'部分追踪','Eye tracking unavailable':'眼部追踪不可用',
    'Observing blink pattern':'正在观察眨眼情况','Blink or closure cues detected':'检测到眨眼或闭眼提示',
    'No active eye cues':'当前无眼部提示','No active cues':'当前无提示',
    'Keep both eyes visible to the front camera.':'请让前置摄像头看到双眼。',
    'Keep your eyes visible while the observation window fills.':'观察期间请让双眼保持可见。',
    'No blink or closure reminders are active.':'当前没有眨眼或闭眼提醒。',
    'Waiting for tracked time':'等待追踪数据','Start a session to set your reference.':'开始监测以建立参考姿势。',
    'The large score is the time-weighted session average of the available live subscores below, including Eyes. Each observed interval has equal-weight subscores; longer intervals contribute proportionally more time. Pauses, missing scores, and observation gaps are excluded. The average stays visible during pauses or tracking loss and resets for a new session. Individual scores show the current position. Posture and geometry grip scores compare with your reference. Image grip ratings come from rated examples; pen-recognition match scores appear separately and are excluded from the session average. Eyes subtracts 25 for each active blink or closure cue after observation. These scores do not measure health or verify grip correctness.':'大分数是下方实时子分数（包括眼部）的时间加权平均值。每个观测时段内的子分数权重相同，较长时段按持续时间贡献更多。暂停、缺失分数和观测中断不计入平均值。暂停或追踪丢失时仍显示平均分，新监测开始时重置。各项分数显示当前位置。姿势和几何握笔分数与个人参考姿势比较；图像握笔评分来自已评分样本，识笔匹配分单独显示，不计入本次平均分。完成观察后，每出现一项眨眼或闭眼提示，眼部分数扣 25 分。这些分数不衡量健康状况，也不能确认握笔姿势正确。',
    'Resume when you’re ready.':'准备好后继续。','Keep your movement relaxed.':'保持自然放松。',
    'No active reminders. Suggestions appear in your live guidance.':'当前没有提醒。建议会显示在实时指导中。',
    'Reminders are quiet. Live guidance continues above.':'提醒已静音。上方仍会显示实时指导。',
    'Waiting to reconnect':'等待重新连接','Server disconnected':'服务器已断开连接',
    'One bar per active minute. All configured posture views must be tracked; missing tracking is never counted as near reference. Sampled once per second.':'每个柱形代表一分钟有效时长。必须追踪到所有已配置的姿势视角；追踪缺失不会计为接近参考姿势。每秒采样一次。',
    'One bar per day with saved sessions, grouped by session start date. Each bar shows the share of active time.':'按监测开始日期汇总已保存的记录，每个柱形表示当天有效时长的占比。',
    'Demo · sessions are not saved':'演示 · 不保存监测记录','Session saving is off':'监测记录保存已关闭',
    'View':'查看','Duration (seconds)':'持续时间（秒）','Near reference':'接近参考姿势',
    'Elbow spread':'手肘外展','Shoulder raise':'肩部抬高','Camera proximity':'摄像头距离',
    'Wrist alignment':'手腕对齐','Thumb–index gap':'拇指与食指间距','Not tracked':'未追踪',
    'Adjust your position.':'请调整姿势。','Complete setup to see current measurements.':'完成设置后查看当前测量结果。',
    'Camera unavailable':'摄像头不可用','Monitoring paused':'监测已暂停','Eyes unavailable':'眼部追踪不可用',
    'No current assessment is available.':'当前没有可用的评估。','Hold comfortably upright while your reference is learned.':'请舒适坐直，等待系统学习参考姿势。',
    'Calibrating':'正在校准','Hold comfortably still':'请舒适地保持静止','Waiting for tracking…':'等待追踪…',
    'Waiting for fresh hand measurements from the server.':'等待服务器提供新的手部测量结果。',
    'Connection lost. Waiting for fresh measurements.':'连接已中断，等待新的测量结果。',
    'Session details unavailable.':'监测详情不可用。','Analytics history is unavailable while the server is disconnected.':'服务器断开连接时无法查看历史统计。',
    'Local history cleared.':'本地历史记录已清除。','This browser does not support spoken reminders.':'此浏览器不支持语音提醒。',
    'Saving…':'正在保存…','All changes saved':'所有更改已保存','Check the highlighted value':'请检查标出的数值',
    'Connection lost. Previous measurements are no longer current.':'连接已中断。之前的测量结果已失效。',
    'Detection unavailable · disconnected':'检测不可用 · 已断开连接','Live measurements unavailable':'实时测量不可用',
    'Server disconnected. Reminders are unavailable.':'服务器已断开连接，提醒不可用。',
    'The local server is disconnected. Start it again to resume.':'本地服务器已断开连接，请重新启动后继续。',
    'Assessing the photo with the local image model…':'正在使用本地图像模型评估照片…',
    'Choose a JPEG, PNG or WebP photo smaller than 16 MB.':'请选择小于 16 MB 的 JPEG、PNG 或 WebP 照片。',
    'Could not read this photo.':'无法读取此照片。','Photo assessed. Scores and matches are shown below.':'照片评估完成，评分和匹配结果见下方。',
    'Photo ready. Assessment runs on this computer.':'照片已准备好，评估将在此电脑上进行。',
    'Rated example saved. Assess a photo again to use the updated image library.':'评分样本已保存。请重新评估照片以使用更新后的图像库。',
    'No local speech voice is available. Install an OS voice or try another browser.':'没有可用的本地语音。请安装系统语音或尝试其他浏览器。',
    'Speech was interrupted or blocked. Use Enable & test voice to retry.':'语音已中断或被阻止。请点击“启用并测试语音”重试。',
    'Voice ready. Automatic warnings follow your saved reminder settings.':'语音已就绪。自动警告将遵循已保存的提醒设置。',
    'Set up tracking':'设置追踪','Start a session and keep the required landmarks visible.':'开始监测，并让所需的身体关键点保持可见。',
    'Posture camera':'姿势摄像头','Follow the setup guide to establish your comfortable reference.':'按照设置指引建立舒适的参考姿势。',
    'Start hand tracking to measure writing.':'开启手部追踪以测量书写状态。',
    'Fingers: Not assessed · Wrist: Not assessed · Pen: Not assessed · Sensor force: Not assessed':'手指：尚未评估 · 手腕：尚未评估 · 笔：尚未评估 · 传感器力度：尚未评估',
    'Learned change detector: no prediction. Train and load a model using labeled recordings.':'学习型变化检测器：暂无预测。请使用标注记录训练并加载模型。',
    'Force: connect a calibrated sensor to measure grip or tip force.':'力度：连接校准后的传感器以测量握笔或笔尖力度。',
    'Demo camera images are synthetic. Choose a real photo to test the image model.':'演示摄像头图像为模拟画面。请选择真实照片来测试图像模型。',
    'Learning your reference':'正在学习参考姿势','No tiredness cues':'没有疲劳提示','Setting up':'正在设置',
    'Eyes tracked':'眼部追踪正常','Available':'可用','Torso lean':'躯干倾斜','Forward head':'头部前伸'
  };
  const patterns = [
    [/^(\d+) (minutes?)$/, n => `${n[1]} 分钟`],
    [/^(\d+) rated image examples · (\d+) grip labels$/, n => `${n[1]} 个已评分图像样本 · ${n[2]} 个握笔标签`],
    [/^(\d+) active reminders?$/, n => `${n[1]} 条当前提醒`],
    [/^Snoozed · (.+) left$/, n => `提醒已暂停 · 剩余 ${n[1]}`],
    [/^Reminder after (\d+) min\. Movement resets the timer\.$/, n => `${n[1]} 分钟后提醒。活动会重置计时器。`],
    [/^(\d+(?:\.\d+)?)s$/, n => `${n[1]} 秒`],
    [/^(\d+)m$/, n => `${n[1]} 分钟`],
    [/^(\d+)h (\d+)m$/, n => `${n[1]} 小时 ${n[2]} 分钟`],
    [/^(\d+(?:\.\d+)?) \/ min$/, n => `${n[1]} 次/分钟`],
    [/^(\d+) out of 100$/, n => `${n[1]} / 100`],
    [/^Paused · (.+) scored$/, n => `已暂停 · 已评分 ${n[1]}`],
    [/^Ended · (.+) scored$/, n => `已结束 · 已评分 ${n[1]}`],
    [/^(.+) scored$/, n => `已评分 ${n[1]}`],
    [/^(.+) · Partial tracking$/, n => `${translate(n[1])} · 部分追踪`],
    [/^(.+) · (\d+)\/100$/, n => `${translate(n[1])} · ${n[2]}/100`]
  ];
  function translate(value) {
    if (Object.hasOwn(zh, value)) return zh[value];
    for (const [pattern, make] of patterns) {
      const match = value.match(pattern);
      if (match) return make(match);
    }
    return value;
  }
  let language;
  try { language = localStorage.getItem(key) === 'zh-CN' ? 'zh-CN' : 'en'; } catch (_) { language = 'en'; }
  const originals = new WeakMap();
  const translated = new WeakMap();
  const attributes = ['aria-label', 'placeholder', 'title'];
  function updateText(node) {
    const value = node.nodeValue;
    if (!value.trim()) return;
    if (value !== translated.get(node)) originals.set(node, value);
    const original = originals.get(node) || value;
    const next = language === 'zh-CN' ? original.replace(/^(\s*)(.*?)(\s*)$/s, (_, a, b, c) => a + translate(b) + c) : original;
    translated.set(node, next);
    if (value !== next) node.nodeValue = next;
  }
  function updateAttribute(element, name) {
    if (!element.hasAttribute(name)) return;
    let record = originals.get(element);
    if (!record || typeof record !== 'object') { record = {}; originals.set(element, record); }
    let last = translated.get(element);
    if (!last || typeof last !== 'object') { last = {}; translated.set(element, last); }
    const value = element.getAttribute(name);
    if (value !== last[name]) record[name] = value;
    const next = language === 'zh-CN' ? translate(record[name]) : record[name];
    last[name] = next;
    if (value !== next) element.setAttribute(name, next);
  }
  function updateTree(root) {
    if (root.nodeType === Node.TEXT_NODE) { updateText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) attributes.forEach(name => updateAttribute(root, name));
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.TEXT_NODE) updateText(node);
      else attributes.forEach(name => updateAttribute(node, name));
    }
  }
  function applyLanguage() {
    document.documentElement.lang = language;
    document.getElementById('language').value = language;
    updateTree(document);
  }
  document.getElementById('language').addEventListener('change', event => {
    language = event.target.value === 'zh-CN' ? 'zh-CN' : 'en';
    try { localStorage.setItem(key, language); } catch (_) { /* The selection still works for this page. */ }
    applyLanguage();
  });
  applyLanguage();
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') updateText(record.target);
      else if (record.type === 'attributes') updateAttribute(record.target, record.attributeName);
      else for (const node of record.addedNodes) updateTree(node);
    }
  }).observe(document, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: attributes});
})();
