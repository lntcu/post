import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const root='/Users/user/Developer/experiment/post';
const p=Presentation.create({slideSize:{width:1280,height:720}});
const data=[
['智享健康','让学习中的身体信号更容易被看见','Making wellbeing cues easier to notice while studying','新加坡与中国学生合作项目','A Singapore–China student collaboration'],
['目录','01  问题与目标     02  方案与功能','01  Problem & goals     02  Solution & features','03  演示     04  局限与展望     05  资料来源','03  Demo     04  Limits & next steps     05  Sources'],
['学习时，我们容易忽略身体信号','久坐与持续看屏幕','Long sitting and extended screen use','专注学习时，姿势变化与休息需求容易被忽略。','While studying, changes in posture and the need for breaks can go unnoticed.'],
['两个学习场景，同一个需求','屏幕学习','Screen-based study','书写学习','Handwriting'],
['我们的目标','发现变化','Notice changes','鼓励休息与舒适习惯，提供及时、温和的反馈。','Encourage breaks and comfortable habits with timely, gentle feedback.'],
['我们的方案','摄像头观察 · 个人参考 · 持续变化 · 提醒','Camera observation · Personal reference · Sustained change · Reminder','在学生自己的电脑上处理画面。','Process camera frames on the student’s own computer.'],
['姿态监测：与自己的参考比较','头部与肩部变化','Head and shoulder changes','正面查看倾斜与转动，侧面补充头部前移观察。','The front view tracks tilt and turn. A side view adds forward-head cues.'],
['眼部提示：把休息变成可见的选择','眨眼与闭眼线索','Blink and eye-closure cues','提供眨眼、移开视线或休息建议，不能判定疲劳。','Suggest blinking, looking away or resting. These cues do not determine fatigue.'],
['书写监测：关注个人变化','手部参考校准','Personal hand-reference calibration','比较手部特征变化，不判断握笔是否“标准”。','Compare hand-feature changes without certifying a “correct” grip.'],
['提醒由你掌握','灵敏度 · 延迟 · 暂停提醒','Sensitivity · Delay · Snooze','支持安静时段与分类提醒，减少重复打扰。','Quiet hours and separate reminder controls reduce repeated interruptions.'],
['隐私与控制','画面在本机处理','Camera frames stay on the computer','暂停会释放摄像头。可选记录仅保存本地数值数据。','Pausing releases cameras. Optional recordings store numeric data locally.'],
['从摄像头到仪表盘','Python + OpenCV + MediaPipe','Python + OpenCV + MediaPipe','提取可见特征，校准个人参考，再显示变化与提醒。','Extract visible features, calibrate a personal reference, then show changes and reminders.'],
['现场演示','① 校准参考   ② 展示变化   ③ 休息与恢复','① Calibrate   ② Show a change   ③ Take a break and resume','演示模式使用合成数据，仅展示界面与提醒流程。','Demo mode uses synthetic data to show the interface and reminder flow.'],
['当前局限','看得见，才能测量','Measurements need visible features','光线、遮挡与角度影响追踪。尚无真实用户准确率结论。','Lighting, occlusion and camera angle affect tracking. Real-user accuracy is not established.'],
['下一步：在真实学习中验证','学生测试 · 多样化数据 · 操作优化','Student testing · Diverse data · Clearer guidance','用不同参与者评估误报与变化识别，再改进体验。','Evaluate false alerts and change detection with different participants, then refine the experience.'],
['资料来源','原始项目演示稿《少字版》','Original project presentation: 少字版.pptx','产品文档 README.md：功能、校准、隐私与已知局限。','Product README.md: features, calibration, privacy and known limitations.']
];
function box(s,x,y,w,h,fill,geo='rect'){return s.shapes.add({geometry:geo,position:{left:x,top:y,width:w,height:h},fill,line:{fill:'none',width:0}})}
function txt(s,t,x,y,w,h,size,color='#102F36',bold=false){let a=box(s,x,y,w,h,'none','textbox');a.text=t;a.text.style={fontFamily:'Arial',fontSize:size,color,bold};return a;}
for(let i=0;i<data.length;i++){
 let s=p.slides.add(),d=data[i],dark=i===0||i===5||i===14;s.background.fill=dark?'#102F36':'#F5F7F3';let c=dark?'#FFFFFF':'#102F36',mut=dark?'#B7D4D0':'#536A70';
 box(s,64,64,56,7,'#28B6A5');txt(s,d[0],64,102,1150,100,i===0?66:48,c,true);
 txt(s,d[1],64,250,1090,72,38,c,true);txt(s,d[2],64,330,1090,65,28,mut);
 box(s,64,432,1100,2,dark?'#35575C':'#CEE0DA');txt(s,d[3],64,470,1090,74,29,c);txt(s,d[4],64,552,1090,72,23,mut);
 txt(s,String(i+1).padStart(2,'0'),1160,654,65,30,18,mut);
}
await fs.mkdir(root+'/.presentation-build/previews',{recursive:true});
for(let i=0;i<p.slides.items.length;i++){let b=await p.export({slide:p.slides.items[i],format:'png',scale:0.6});await fs.writeFile(root+'/.presentation-build/previews/'+i+'.png',new Uint8Array(await b.arrayBuffer()));}
await(await PresentationFile.exportPptx(p)).save(root+'/.presentation-build/draft.pptx');
const {finalizePresentation}=await import('/Users/user/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations/container_tools/artifact_tool_utils.mjs');
console.log(await finalizePresentation({integrityValidatorPath:'/Users/user/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:'/Users/user/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations/container_tools/inspect_presentation_layout_geometry.py',workspaceDir:root,candidatePath:root+'/.presentation-build/draft.pptx',finalPath:root+'/output/智享健康_双语展示.pptx',pythonExecutable:'/Users/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',explicitTotalSlideCount:16,expectedSlideSizeEmu:'12192000,6858000',fontPolicy:{basis:'design',families:['Arial','Aptos']},verifyArtifactToolImport:true,receiptPath:root+'/.presentation-build/validation.json'}));
