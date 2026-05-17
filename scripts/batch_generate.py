"""
批量生成应用商店封面图（packy / gpt-image-2）

核心机制：
  1. ICON 颜色提取 → 提升为高饱和高明度品牌色
  2. S_INTRO/HUMAN_DESC/SUBJECT_POOL 三层主体推导
  3. 分类驱动风格分配：每个分类有专属风格池，按行号轮选
     - 母婴.儿童：[4羊毛毡(主推), 9粘土C4D, 3CG厚涂, 2 3D立体]
     - 其他分类：见 CATEGORY_RECOMMENDED_STYLES
  4. 分类驱动构图分配：见 CATEGORY_RECOMMENDED_COMPOSITIONS
  5. 品牌层级识别：高端(大厂/国企)→克制电影感；精品(国际授权)→精品插画感
  6. 内容安全硬性约束：货币/IP/LGBT/医疗金融/视觉成熟度
  7. 图片压缩 ≤200KB，输出文件名 = PACKAGE_NAME.jpg

用法：
  python batch_generate.py --csv X --start 1 --end 20 --outdir Y
  python batch_generate.py --csv X --start 1 --end 20 --style 9 --outdir Y  # 强制风格
"""

import argparse
import base64
import colorsys
import csv
import io
import os
import random
import ssl
import time
import urllib.request

import requests
from PIL import Image

# ── 项目根目录（用于解析相对路径默认值） ─────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 配置（敏感信息走环境变量；路径可被 CLI 覆盖） ──────
# API Key 三级回退：
# 1) 环境变量 PACKY_API_KEY               ← 推荐
# 2) 项目根 .env 文件（需 python-dotenv） ← 适合本地长期使用
# 3) 下方 INTERNAL_FALLBACK_KEY 常量      ← 仅用于「内部分发版」开箱即用
#
# ⚠️ 安全提醒：
#   - 公开分发（GitHub / 网盘 / 邮件给外部）的版本中，INTERNAL_FALLBACK_KEY 必须为空
#   - 内部分发版由 build_release.sh internal <sk-xxx> 自动注入，结束后自动恢复为空
#   - 永远不要手动把 Key 提交到 git
INTERNAL_FALLBACK_KEY = ""   # ← 公开版恒为空；内部版打包时由 build_release.sh 临时注入

def _load_api_key() -> str:
    # 尝试加载 .env（可选依赖，未安装则忽略）
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    except Exception:
        pass
    key = os.environ.get("PACKY_API_KEY", "").strip()
    if not key and INTERNAL_FALLBACK_KEY:
        key = INTERNAL_FALLBACK_KEY.strip()
        print("ℹ️  使用内部分发版内置 Key（仅限内部使用）")
    if not key:
        raise RuntimeError(
            "未找到 PACKY_API_KEY。请二选一配置：\n"
            "  方式 A：export PACKY_API_KEY='sk-xxxxx'\n"
            "  方式 B：在项目根创建 .env 文件，写入 PACKY_API_KEY=sk-xxxxx\n"
            "          （需先 pip install python-dotenv）\n"
            "参考 .env.example 模板。"
        )
    return key

PACKY_KEY  = ""                    # 在 main() 入口惰性加载，避免 import 时直接抛错
PACKY_BASE = os.environ.get("PACKY_BASE", "https://www.packyapi.com/v1")
MODEL      = os.environ.get("PACKY_MODEL", "gpt-image-2")
SIZE       = "1536x1024"           # 横版 16:10，gpt-image-2 支持的最宽尺寸
CSV_PATH   = os.path.join(PROJECT_ROOT, "data", "input.csv")     # 默认项目内相对路径
OUT_DIR    = os.path.join(PROJECT_ROOT, "output", "covers")      # 默认项目内相对路径
MAX_KB     = 200                   # 输出文件上限

# ── 点缀色色彩关系（随机选用，避免固定青色）──────────────
# 每次 build_prompt 时随机取一种，注入 prompt 中
ACCENT_MODES = [
    "互补色（色相差150-180°，如品牌红→青绿/蓝绿，品牌蓝→橙/橙红，品牌黄→紫/蓝紫，品牌绿→洋红，强烈跳色对比）",
    "对比色（色相差120-150°，如品牌红→蓝绿，品牌蓝→黄橙，品牌橙→蓝紫，中强度对比活力而不冲突）",
    "撞色（色相差90-120°，如品牌红→紫，品牌蓝→黄绿，品牌橙→蓝，时尚跳跃的高能色彩碰撞感）",
    "邻近对比色（色相差60-90°，如品牌红→黄，品牌蓝→绿，品牌橙→绿，色相相近又有变化，协调灵动）",
]

# ── 现代扁平插画构图（5种，随机取用）─────────────────────
MEMPHIS_COMPOSITIONS = [
    "主体居中饱满式：1-2个紧密组合的主体插画作为一个整体团块位于画面绝对正中央（水平垂直均居中），整体占画面55-70%，2个主体必须物理接触/重叠形成不可分割的视觉团，严禁两个主体分开放置，周围圆球和星芒紧凑围绕",
    "主体居中仰角式：整体从画面水平中央偏下起向上延伸，营造仰角冲击感，水平方向严格居中，主体整体占画面高度60-70%，2个主体上下紧密叠放形成单一视觉团，顶部留适当呼吸空间",
    "主体居中偏上式：整体团块位于水平中央+垂直偏上1/3处，2个主体紧密叠放为单一视觉团，整体占画面55-65%，底部留出较多空白区域供圆球和星芒散落点缀",
    "主体居中前倾式：整体略向观者方向前倾10-15°，位于画面正中央，2个主体紧贴无间隙形成不可分割视觉团，整体占画面60-70%，前倾姿态增强空间立体感",
    "主体居中充满式：整体团块充满画面中央区域，水平垂直均居中，2个主体重叠融合，整体占画面65-75%，圆球和星芒散布在主体四周边缘空白处",
]

# ── 现代扁平插画氛围（3种，随机取用）— 来自 style22 Corporate Memphis ──
MEMPHIS_ATMOSPHERES = [
    "氛围-放射爆发型：以主体物为原点向四周发射几何线条、星形和气泡，从主体后方延伸出放射状色块（Ray lines）和发散的小几何粒子，与速度线协同营造能量爆发感，使用背景同色系深一阶",
    "氛围-磁场轨迹型：背景装饰元素表现为平滑的等粗曲线（Path lines），沿椭圆轨道环绕主体物向外扩散，营造连接与流动感，使用背景同色系深一阶",
    "氛围-几何底座型：画面底部有同色系深一阶的厚实几何块面或重叠半圆作为几何底座，承托主体根部，高度约10-15%，营造稳重生长感",
]

# ── 11种构图矩阵（来自 SKILL B.md）──────────────────
# (构图名, 视角描述, 主体占比)
COMPOSITIONS = [
    ("宏大仰视式",   "极低角度仰视，主体渺小位于画面中央，天空占画面60-70%云雾层次",   "主体占画面30-40%"),
    ("低角冲击式",   "低角度俯视，地面纹理向远处延伸，主体位于画面中央，前景冲击力强",   "主体占画面30-40%"),
    ("中心爆发式",   "中心点放射构图，能量向外扩散，主体位于画面中央，四周能量波纹粒子离心", "主体占画面30-40%"),
    ("叙事留白式",   "主体位于画面中央，背景左右不对称留白，环境元素偏向一侧营造叙事感，前简后繁", "主体占画面45-60%"),
    ("对角线动态式", "主体位于画面中央，背景对角线光轨元素流向主体，运动感由背景元素承载", "主体占画面45-60%"),
    ("中心稳重式",   "主体位于画面中央微偏上，对称平衡，四周环绕弱散射光",             "主体占画面45-60%"),
    ("S曲线探索式",  "主体位于画面中央，背景S形光流路径环绕主体延伸，前景清晰中景过渡背景梦幻", "主体占画面45-60%"),
    ("特写冲击式",   "极近距离特写，主体充满画面居中，背景完全虚化仅保留色彩氛围",       "主体占画面70-80%"),
    ("英雄正面式",   "正面平视，主体居中充满画面中央，背景简洁渐变主体边缘发光",         "主体占画面70-80%"),
    ("仰角特写式",   "低角度仰视特写，主体压迫感强位于画面中央，背景天空或光晕主体底部延伸出画面", "主体占画面70-80%"),
]

# ── 12种风格矩阵（来自 SKILL B.md）──────────────────
# (索引, 风格名, 色调规则, 光线, 仅限: None/baby)
# 构图在 build_prompt 中从 COMPOSITIONS 随机取用
STYLES = [
    (1,  "写实3DCG画风格",
         "图标主色{color}映射哑光珐琅质感（饱和度S 45-62%，明度L 50-65%），表面哑光无镜面反射，色彩中饱和鲜润不刺眼，背景取主色同色系中饱和版（S 40-58%，L 45-60%），背景层次由两类元素营造：①超大面积同色系柔光漫射（光区面积占背景50%以上，光与背景之间无任何可见边界——通过极超大范围羽化完全融化消失如浓雾散射，严禁出现任何光边轮廓线或可辨识的光束形状）；②极大景深完全模糊的背景元素（根据画面场景内容自然选择匹配的物体形态，模糊至仅剩色彩轮廓无任何细节，营造纵深感）；背景两类元素色差均控制在背景色10%以内，严禁流线光轨；【活力光源】在主体背光面/暗部边缘施加一道互补色调（色相差≥120°）的柔和环境反射光（色温偏移，S 45-65%，低饱和柔和不刺眼），主体功能屏幕/发光部件发出带互补色温的内发光光晕，互补色完全依附于光影层融入画面，严禁以独立漂浮几何体/单独装饰形状呈现",
         "大面积柔光箱漫射主光、轻柔过渡阴影（无硬边），背景打同色系有色环境光（与背景色调一致），严禁镜面高光Specular、严禁强边缘反光、严禁硬阴影、严禁白色泛光",
         None),
    (2,  "3D立体风格",
         "图标主色{color}降饱和映射磨砂金属质感（S 30-48%，L 45-60%），表面磨砂哑光微粒感，镜面反射率极低，背景取主色同色系低饱和版（S 25-42%，L 42-56%），背景层次由两类元素营造：①超大面积同色系柔光漫射（光区面积占背景50%以上，光与背景之间无任何可见边界——通过极超大范围羽化完全融化消失如浓雾散射，严禁出现任何光边轮廓线或可辨识的光束形状）；②极大景深完全模糊的背景元素（根据画面场景内容自然选择匹配的物体形态，模糊至仅剩色彩轮廓无任何细节，营造前后纵深层次）；背景两类元素色差均控制在背景色8%以内，严禁流线光轨；【活力光源】主体背面/侧面施加一道互补色调（色相差≥120°）的柔和逆光边缘光（轮廓光rim light），色温偏向互补色（S 40-60%，柔和不刺眼），磨砂面微粒漫反射中隐含互补色光感，功能屏幕内发光携带互补色温暖色调；互补色仅通过光的形式融入，严禁以独立漂浮几何元素/装饰形状呈现",
         "单侧大柔光漫射（低对比度），仅保留极薄轮廓光勾勒形体边缘，背景有色环境光与背景色调一致，严禁强边缘反射光、严禁镜面高光Specular、严禁多光源叠加、严禁白色泛光",
         None),
    (3,  "CG厚涂风格",
         "图标主色{color}（S 58-76%，L 52-68%），背景取主色深饱和版本（S 保持60%以上，L 42-55%），高光取主色高明度方向提亮，色彩鲜明不发灰；【冷暖对比活力】利用CG厚涂冷暖分色特点——主体受光面为主色暖调高光，背光面/阴影边缘渗入互补色冷调（色相差≥120°，S 55-70%，低明度），形成冷暖撞色的CG厚涂光感；互补色融合在笔触光影与阴影色温中，严禁以独立漂浮几何元素/道具呈现",
         "强侧硬光、笔触光影、冷暖分色（主光暖调/阴影冷调互补色渗入）、硬边阴影",
         None),
    (4,  "羊毛毡风格",
         "图标主色{color}映射高明度柔和色系（S 30-55%，L 70-85%），背景高明度低饱和",
         "柔和漫射暖光、毛边逆光、低对比无硬影",
         "baby"),
    (5,  "壁画质感风格",
         "图标主色{color}映射复古艺术色调（S 52-68%，L 52-65%），色彩饱满鲜明有层次感，背景取主色同色系低明度版（L 不低于45%，S 保持55%以上），禁止发灰发黑；【复古光感活力】天窗丁达尔散射光带有互补色（色相差≥120°）的冷暖色温偏移——光束本体为主色系暖调，光束边缘/散射光晕渗入互补色冷调微光（S 45-60%，朦胧不刺眼），主体物材质表面在受光与背光交界处出现互补色彩虹般的薄膜反射光；互补色通过光学现象自然融入，严禁以独立漂浮元素/道具形式呈现",
         "复古大面积漫射侧光（光区与背景完全融合过渡，无可见硬边分界线）、天窗丁达尔效应（光束边缘必须大范围柔化扩散如浓雾中散射的朦胧光晕，严禁出现任何清晰可辨的硬边光束轮廓线或锐利光线条纹）、暖调艺术光影",
         None),
    (6,  "轻量超现实3D商业插画",
         "图标主色{color}中高饱和（S 50-65%）作主色调，背景低饱和极高明度（L 80-92%），整体清新通透活泼；背景中层叠放1-2个与画面内容相关的超大体量元素（场景道具/主体物同款物件/有机几何形），进行极深度高斯模糊处理（模糊至仅剩极淡色彩轮廓无任何细节），与背景白色调色差控制在8%以内，若隐若现营造纵深感和背景充实度，不得出现大片空白区域，严禁过于清晰或增加杂乱感；【清新光感活力】主体物边缘受到互补色调（色相差≥120°）的柔和侧面环境光照射，在高光轮廓处呈现淡淡的互补色色温偏移（S 40-55%，浅淡通透），发光屏幕/功能部件的内发光带有互补色温暖色调；互补色以光线色温方式自然渗入，严禁以漂浮几何形/独立装饰元素呈现",
         "正面加顶部品牌色有色柔和漫射光（带品牌色色温，禁止纯白光源），无硬阴影，边缘带轻微有色柔光",
         None),
    (7,  "3D极简玻璃拟态App Store风格",
         "图标主色{color}（S 48-68%，L 58-75%），背景同色系极简双色渐变（L 不低于55%），干净克制通透，禁止荧光色；主体物本身具备玻璃/水晶质感（折射高光/透明边缘/焦散光斑），主体直接置于干净背景上；【折射活力】主体物边缘色散出点缀色（色相差≥120°）彩虹薄边（S 50-70%，细腻通透），焦散光斑自然散落在主体周围背景上；严禁以漂浮独立几何形呈现点缀色",
         "焦散效果、折射光、软阴影、全局照明GI、边缘轮廓光",
         None),
    (8,  "新拟物主义2.0充气3D风格",
         "图标主色{color}延伸柔和梦幻渐变（S 52-68%，L 58-72%），背景取主色明亮版（L 不低于52%），整体饱满通透，禁止高饱和荧光色；【充气透光活力】充气体为半透明材质，背光侧透出互补色（色相差≥120°）的透射光（S 45-60%，柔和梦幻），充气体表面最薄处/边缘处呈现互补色冷暖光晕过渡，类似气球透光的自然色彩变化；互补色通过半透明材质的光线透射自然呈现，严禁以漂浮独立几何元素呈现",
         "丁达尔效应（大范围柔和弥散，无硬边无光束轮廓线，光区与背景完全融合过渡）、轻微物理折射（柔光漫射型，严禁硬边折射光束）、边缘极薄轮廓微光（柔和无锐边）；严禁背景出现密集缠绕曲线/多条盘旋流线/复杂螺旋装饰，背景简洁克制",
         None),
    (9,  "3D粘土C4D潮流玩具风格",
         "图标主色{color}同色系渐变（S 58-72%，L 55-68%），背景取主色明亮饱和版均匀单色（L 不低于52%），色彩活泼饱满，禁止纯度极高荧光感，严禁背景出现径向渐变光晕/圆形聚光/中心亮斑，背景色调必须整体均匀一致；背景中层叠放1-2个与画面内容相关的超大体量物件（如同款玩具剪影/场景道具/抽象圆球），进行极深度高斯模糊处理（模糊至仅剩色彩轮廓，无任何细节可辨），与背景色差控制在12%以内，若隐若现填充背景纵深，严禁过于清晰或增加画面杂乱感；【粘土光感活力】粘土主体的侧光面/背光面边缘受到互补色（色相差≥120°）的轮廓逆光照射（轮廓光rim light，S 50-65%，柔和饱满），屏幕/功能显示元素的内发光带有互补色温暖调；互补色通过打光方式融入，严禁以漂浮独立几何形/装饰元素呈现",
         "单侧大面积柔光漫射（左侧或右侧45°入射），光区均匀扩散无渐变光圈，背景环境光统一无明暗分界，边缘轮廓光轻柔勾勒主体，严禁径向聚光/舞台聚光/背景中心发光效果",
         None),
    (10, "潮流3D艺术混合材质拟物风格",
         "图标主色{color}（S 50-68%，L 55-70%），背景取主色深饱和版（L 不低于42%，S 保持55%以上），内部自发光强调色彩活力，严禁背景发黑发灰；【混合材质光感活力】主体内部自发光光源本体为主色系，但光线向外散射时色温逐渐偏移向互补色（色相差≥120°），在主体物外轮廓/透明材质边缘形成互补色发光晕圈（S 55-70%），金属与玻璃材质交界面的折射产生互补色色散；互补色通过自发光扩散与材质折射自然呈现，严禁以漂浮独立装饰几何体呈现",
         "柔和全局光加强边缘逆光加内部自发光",
         None),
    (11, "2D扁平插画Rounded Geometric Futurism数字颗粒质感风格",
         "品牌色{color}约60%（中高饱和S 52-72%，明度L 55-72%，避免过亮刺眼），辅色约20%用于主体局部细节，点缀色约10%用于主体边缘高光，全画不超过4色，色彩明快活泼",
         "图形化光影、主体轮廓局部边缘发光、硬边色块阴影、全画叠加低密度数字颗粒加半调网点质感",
         None),
    (12, "现代扁平插画风格",
         "【配色系统——严格遵守，共4色】"
         "①背景主色（≥65%铺满全画）：品牌色{color}高饱和鲜亮纯色（S 82-92%，L 45-65%），完全平涂干净背景，无任何纹理渐变；"
         "②主对比色（约20%，主体物/大色块）：选1个与品牌色强对比的鲜亮色（色相差90-150°，S 80-90%，L 42-62%），用于主体物主色和关键图形；"
         "③高亮白/近白（约10%，反光/高光面）：白色或极高明度色（L 92-98%），用于主体物受光面和小圆球；"
         "④主色深版阴影（约5%）：与主色相同色相但明度降低（L 18-32%，同色相），专用于主体物的偏移投影效果，制造扁平立体感；"
         "严禁超过4种主色（含白不含黑），严禁灰调/莫兰迪/大地色/任何渐变，所有色块纯色平涂",
         "纯平涂无写实光影，无复杂渐变，无3D渲染感，偏移投影使用主色深版（同色相降明度），严禁复杂阴影/羽化",
         None),
]

# ── 分类主体池（来自 SKILL B.md 关键主体池调整 + 分类专属前景道具表）──
# key = CSV NAME 字段；value = 可选主体列表，生成时随机取一个
SUBJECT_POOL = {
    # ── 游戏类 ──────────────────────────────────────
    "动作冒险":  ["战刃武器与爆炸特效碎片", "盔甲护盾与能量冲击波", "英雄剪影与漫天飞舞的战场粒子"],
    "飞行射击":  ["战斗机与导弹尾焰轨迹", "激光炮与能量护盾", "宇宙飞船与星际碎片爆炸"],
    "角色扮演":  ["魔法法杖与神秘符文光阵", "宝剑盔甲与魔法宝石", "召唤之书与漂浮能量水晶"],
    "经营策略":  ["城市建筑群与资源图标", "金币宝箱与地图网格", "工厂齿轮与成长曲线"],
    "休闲益智":  ["彩色方块与消除爆炸特效", "可爱道具与星星奖励", "拼图碎片与彩虹弧线"],
    "棋牌游戏":  ["扑克牌扇形展开与筹码", "棋子与棋盘方格光效", "麻将牌与金色胡牌特效"],
    "体育竞速":  ["赛车与速度线轨迹", "运动鞋与终点冲刺光效", "足球篮球与运动轨迹弧线"],
    "其他游戏":  ["游戏手柄与奖杯", "像素角色与像素爆炸粒子", "宝箱开启与金色光芒爆发"],
    # ── 应用软件类 ──────────────────────────────────
    "聊天.社交":   ["对话气泡与两个互动人物剪影", "两个爱心漂浮在对话气泡之间", "两个友好的emoji表情围绕聊天气泡"],
    "新闻.阅读":   ["翻开的书页与飘散的文字碎片", "书本与眼睛的视觉组合", "报纸页面与阅读放大镜"],
    "系统.安全":   ["精密齿轮与发光防护盾", "工具箱与锁头的组合", "防护盾与维修扳手"],
    "理财.金融":   ["皮质钱包与金色账单", "通用货币符号与银行卡叠放", "账本翻开页面与金色硬币"],
    "图片图形":    ["画笔与调色板碎片", "人物半身合照与魔法棒", "相机镜头与照片画框"],
    "音乐软件":    ["麦克风与音浪律动灯阵", "耳机线与飞舞的音符", "唱片机与音频播放器"],
    "视频软件":    ["胶片与播放按钮", "电影院幕布与镜头光晕", "屏幕光芒与爆米花筒"],
    "生活.服务":   ["配送包裹与工具", "外卖箱与飞出的美食", "服务人员与配送摩托车"],
    "地图出行":    ["地图碎片与定位图标", "城市地图线条与道路网格", "指南针与旅行箱"],
    "办公.效率":   ["便签纸与回形针", "打开的笔记本与钢笔", "日历与任务清单"],
    "考试.学习":   ["铅笔与试卷角落", "书本与灯泡", "毕业帽与奖杯"],
    "购物.优惠":   ["购物袋与优惠标签", "礼品盒与彩带", "购物车与商品包装"],
    "智能生成":    ["代码符号与星形光点", "AI芯片与数据流星云", "机器人头部与闪光灵感泡泡"],
    "母婴.儿童":   ["彩色积木与玩具碎片", "小熊公仔与彩虹气球", "儿童绘本与蜡笔"],
    "医疗.健康":   ["药片与医疗符号", "心形脉搏线与听诊器", "绿植与健康苹果"],
    "运动.健身":   ["运动器材局部特写", "跑鞋与运动轨迹光线", "哑铃与能量爆发光晕"],
    "桌面.美化":   ["壁纸碎片与渐变色块", "几何图形与调色板", "星空与渐变光带"],
    "系统工具":    ["齿轮与锁头", "工具和便签", "芯片与电路线"],
    "助手工具":    ["工具和便签", "魔法棒与齿轮", "多功能工具箱"],
}

SUBJECT_POOL_DEFAULT = ["应用功能核心视觉符号", "品牌差异化抽象图形", "产品核心场景道具"]

# ── 儿童/母婴品类关键词（命中则允许卡通人物风格）──────────
CHILDREN_KEYWORDS = {"母婴", "儿童", "婴幼", "幼儿", "宝宝", "亲子", "启蒙"}

# ═══════════════════════════════════════════════════════════════
# 品牌层级识别（高端/精品/标准）
# 优先级仅次于 ICON 提取；母婴类一律标准（避免与卡通基调冲突）
# ═══════════════════════════════════════════════════════════════

PREMIUM_BRANDS = {
    "腾讯", "网易", "字节", "字节跳动", "米哈游", "莉莉丝",
    "阿里", "阿里巴巴", "蚂蚁", "支付宝", "淘宝", "天猫",
    "百度", "华为", "小米", "OPPO", "vivo", "联想",
    "京东", "美团", "拼多多", "抖音", "快手", "B站", "哔哩哔哩",
    "央视", "新华社", "人民日报", "中国移动", "中国联通", "中国电信",
    "中国银行", "工商银行", "建设银行", "农业银行", "招商银行",
    "国家", "中央", "总局",
}

QUALITY_BRANDS = {
    "迪士尼", "Disney", "皮克斯", "Pixar",
    "BBC", "国家地理", "National Geographic",
    "牛津", "Oxford", "剑桥", "Cambridge",
    "DK", "RAZ", "新东方", "好未来", "学而思",
    "宝宝巴士", "凯叔讲故事", "洪恩",
}

def detect_brand_tier(app_name, s_intro, human_desc, is_children=False):
    """识别品牌层级：高端 / 精品 / 标准。母婴类一律标准（避免与卡通基调冲突）"""
    if is_children:
        return "standard"
    text = f"{app_name} {s_intro} {human_desc}"
    if any(kw in text for kw in PREMIUM_BRANDS):
        return "premium"
    if any(kw in text for kw in QUALITY_BRANDS):
        return "quality"
    return "standard"

TIER_INJECTION = {
    "premium": (
        "，【品牌层级=高端】电影级质感、精致光影、高端商业视觉、克制配色、专业摄影感构图；"
        "严禁卡通造型、Q版萌系、糖果色高饱和乱炖、可爱化处理、低龄幼稚视觉特征"
    ),
    "quality": (
        "，【品牌层级=精品】精品插画感、国际化视觉风格、成熟视觉调性、专业品质感；"
        "严禁卡通造型、Q版、可爱化萌系、糖果色乱炖、低龄幼稚视觉特征"
    ),
    "standard": "",
}

# ═══════════════════════════════════════════════════════════════
# 内容安全硬性约束（全局注入）
# ═══════════════════════════════════════════════════════════════

SAFETY_CONSTRAINTS = (
    "；【内容安全——硬性禁止，违反作废】"
    "①禁止具体国家货币符号/币种文字/纸币硬币样式/￥$€£符号——涉及货币概念时使用中性通用表达"
    "（如金色硬币、宝箱、钱袋轮廓、礼物盒、抽象金属圆币）；"
    "②禁止知名IP形象/版权角色/卡通人物——米老鼠、唐老鸭、皮卡丘、超级马里奥、海绵宝宝、"
    "小猪佩奇、奥特曼、龙猫、机器猫、漫威/DC英雄等任何已知动漫游戏角色；"
    "③禁止LGBT视觉元素/彩虹旗符号/异装造型/性别模糊化表达；"
    "④禁止暴力血腥、色情擦边、歧视性内容、宗教争议符号；"
    "⑤禁止误导性医疗效果表述、金融收益承诺暗示、赌博暗示视觉元素"
)

MATURE_CONSTRAINT = (
    "；【视觉成熟度——非母婴类严格遵守】画面整体气质必须成熟专业，"
    "严禁低龄化视觉特征——Q版圆滚滚造型、卡通泡泡字体感、幼儿园配色高饱和彩虹乱炖、"
    "幼稚化图形语言、可爱化大眼萌感"
)

# ═══════════════════════════════════════════════════════════════
# 分类驱动风格推荐（按行号轮选，未登记则回退全局轮换）
# 母婴.儿童：羊毛毡为主，叠加 9/3/2 增加多样性
#
# ⚠️ 游戏类全局禁用风格：{7, 8, 12}（PARENT_ID == "游戏" 时一律禁用）
#    - #7  玻璃拟态：透明质感 + 严禁人物，无法承载游戏战斗/史诗调性
#    - #8  充气3D：充气可爱感 + 严禁人物，与游戏对抗调性冲突
#    - #12 Memphis：糖果色营销卡通，与游戏视觉张力彻底不兼容
#    禁用机制为三重保险：① 推荐池预先剔除 ② pick_style_for_category 内部过滤
#                       ③ force_style / 全局轮换路径在 main() 中 while 顺延
# ═══════════════════════════════════════════════════════════════

CATEGORY_RECOMMENDED_STYLES = {
    # ── 应用软件类 ──────────────────────────────
    "母婴.儿童":   [4, 9, 3, 2],  # 羊毛毡(主推) + 粘土C4D + CG厚涂 + 3D立体
    "理财.金融":   [1, 2],
    "考试.学习":   [6, 11, 12],
    "聊天.社交":   [6, 8, 12],
    "新闻.阅读":   [1, 5],
    "视频软件":    [6, 10],
    "购物.优惠":   [1, 6],
    "办公.效率":   [6, 11, 12],  # 加入 12 提升 Memphis 出现率（应用类内 ≈9.5%）
    "医疗.健康":   [6, 8],
    "音乐软件":    [10, 7],
    "地图出行":    [1, 6],
    "生活.服务":   [1, 9],
    "系统工具":    [2, 11],
    "系统.安全":   [2, 11],
    "图片图形":    [7, 11],
    "智能生成":    [10, 7],
    "助手工具":    [2, 11],
    "运动.健身":   [3, 9],
    "桌面.美化":   [7, 11],
    # ── 游戏类（全部避开禁用风格 7/8/12） ────────
    "动作冒险":    [9, 10, 3],
    "飞行射击":    [2, 10],
    "角色扮演":    [3, 10],
    "经营策略":    [1, 6],
    "休闲益智":    [9, 11],
    "棋牌游戏":    [1, 5],
    "体育竞速":    [2, 3],
    "其他游戏":    [1, 9, 10],
    "特色分类":    [9, 10, 3, 1],  # 多元小众游戏（二次元/模拟/沙盒等混合）→ 包容性池
    "音乐舞蹈":    [10, 9, 11],    # 节奏律动：混合材质 + 粘土 + Rounded Geometric
    "打飞机":      [2, 10],        # 飞行射击同义别名，沿用飞行射击风格池
}

GAME_BANNED_STYLES = {7, 8, 12}  # ⚠️ 游戏类全局禁用（详见上方注释）

def pick_style_for_category(category, fallback_style, is_game, row_idx):
    """
    按分类推荐选风格。
    - 命中分类：在推荐列表中按 row_idx 轮选（保持差异化）
    - 未命中：返回 fallback_style（全局轮换值）
    - 游戏类：自动过滤禁用风格 7/8/12
    """
    recs = CATEGORY_RECOMMENDED_STYLES.get(category)
    if not recs:
        return fallback_style, False
    if is_game:
        recs = [s for s in recs if s not in GAME_BANNED_STYLES]
        if not recs:
            return fallback_style, False
    chosen = recs[row_idx % len(recs)]
    return chosen, True

# ═══════════════════════════════════════════════════════════════
# 分类驱动构图推荐（按行号轮选，未登记则回退到随机）
# ═══════════════════════════════════════════════════════════════

CATEGORY_RECOMMENDED_COMPOSITIONS = {
    "母婴.儿童":   ["S曲线探索式", "宏大仰视式"],
    "考试.学习":   ["叙事留白式", "中心稳重式"],
    "视频软件":    ["对角线动态式", "S曲线探索式"],
    "聊天.社交":   ["叙事留白式", "中心稳重式"],
    "新闻.阅读":   ["英雄正面式", "叙事留白式"],
    "购物.优惠":   ["对角线动态式", "英雄正面式"],
    "理财.金融":   ["中心稳重式", "英雄正面式"],
    "办公.效率":   ["叙事留白式", "中心稳重式"],
    "医疗.健康":   ["中心稳重式", "叙事留白式"],
    "音乐软件":    ["S曲线探索式", "对角线动态式"],
    "地图出行":    ["宏大仰视式", "叙事留白式"],
    "生活.服务":   ["宏大仰视式", "叙事留白式"],
    "系统工具":    ["中心稳重式", "叙事留白式"],
    "系统.安全":   ["中心稳重式", "叙事留白式"],
    "图片图形":    ["英雄正面式", "特写冲击式"],
    "智能生成":    ["中心爆发式", "英雄正面式"],
    "助手工具":    ["叙事留白式", "中心稳重式"],
    # 游戏类
    "动作冒险":    ["仰角特写式", "英雄正面式"],
    "飞行射击":    ["低角冲击式", "中心爆发式"],
    "角色扮演":    ["英雄正面式", "仰角特写式"],
    "经营策略":    ["宏大仰视式", "中心爆发式"],
    "休闲益智":    ["低角冲击式", "中心爆发式"],
    "棋牌游戏":    ["中心稳重式", "英雄正面式"],
    "体育竞速":    ["对角线动态式", "低角冲击式"],
    "特色分类":    ["叙事留白式", "中心稳重式", "对角线动态式"],  # 多元包容
    "音乐舞蹈":    ["S曲线探索式", "对角线动态式"],                # 节奏律动
    "打飞机":      ["低角冲击式", "中心爆发式"],                   # 与飞行射击一致
}

def pick_composition_for_category(category, row_idx, all_compositions):
    """按分类推荐选构图，未命中则回退到全量随机"""
    recs = CATEGORY_RECOMMENDED_COMPOSITIONS.get(category)
    if not recs:
        return random.choice(all_compositions), False
    # 在 all_compositions 中找出推荐名匹配的元组
    rec_name = recs[row_idx % len(recs)]
    for comp in all_compositions:
        if comp[0] == rec_name:
            return comp, True
    return random.choice(all_compositions), False

# ── 各风格人物描述：儿童版 & 成熟版 ─────────────────────
# 成熟版通用限制（追加在每条末尾）
_MATURE_BLOCK = "；严禁迪士尼/皮克斯卡通大眼萌感造型、严禁头部比例夸张放大、严禁儿童化圆滚滚脸型、严禁真实照片感人脸毛孔皮肤纹理"

_CHAR_STYLE = {
    # 风格1：写实3DCG
    1: {
        "child":  "，【人物风格】如有人物元素，必须使用迪士尼/皮克斯3D卡通动漫风格——大而有神的眼睛（精细虹膜高光），光滑细腻卡通皮肤（柔和SSS无毛孔），自然流动发型，头部略大于写实比例，表情生动活泼，整体卡通质感与哑光珐琅主体融合；严禁真实照片感人脸、毛孔纹理",
        "mature": f"，【人物风格】如有人物元素，使用成熟3D商业插画人物风格——成人正常头身比例（1:6至1:7），五官精致立体但不夸张，发型时尚符合场景，服装专业得体，表情自信从容，皮肤光洁细腻（SSS柔光质感），整体呈现高端商业插画感与哑光珐琅主体协调{_MATURE_BLOCK}",
    },
    # 风格2：3D立体
    2: {
        "child":  "，【人物风格】如有人物元素，必须使用迪士尼/皮克斯3D卡通动漫风格——大而有神的眼睛（精细虹膜高光），光滑细腻卡通皮肤（柔和SSS无毛孔），自然流动发型，头部略大于写实比例，表情生动活泼，整体卡通质感与磨砂金属场景协调；严禁真实照片感人脸、毛孔纹理",
        "mature": f"，【人物风格】如有人物元素，使用成熟3D商业插画人物风格——成人正常头身比例（1:6至1:7），五官精致立体但不夸张，发型时尚，服装职业化或潮流化，表情稳重自信，皮肤光洁磨砂细腻，整体专业有质感与磨砂金属场景协调{_MATURE_BLOCK}",
    },
    # 风格3：CG厚涂
    3: {
        "child":  "，【人物风格】如有人物元素，使用迪士尼卡通插画风格，表情活泼，厚涂笔触质感",
        "mature": f"，【人物风格】如有人物元素，使用成熟CG厚涂插画人物风格——正常成人比例，笔触光影分明，五官立体有型，服装场景化，表情有张力{_MATURE_BLOCK}",
    },
    # 风格5：壁画质感
    5: {
        "child":  "，【人物风格】如有人物元素，使用复古卡通壁画人物风格，造型可爱圆润",
        "mature": f"，【人物风格】如有人物元素，使用成熟复古壁画插画人物风格——正常成人比例，线条流畅有力，色块分明，表情沉稳有叙事感{_MATURE_BLOCK}",
    },
    # 风格6：轻量超现实3D商业插画
    6: {
        "child":  "，【人物风格】如有人物元素，使用轻松可爱的3D卡通人物风格",
        "mature": f"，【人物风格】如有人物元素，使用轻量超现实3D商业插画人物风格——成人正常比例，简洁几何化面部（无写实毛孔），服装造型感强，整体清新通透活泼但不幼稚{_MATURE_BLOCK}",
    },
    # 风格8：充气3D
    8: {
        "child":  "，【人物风格】如有人物元素，使用充气膨胀卡通人物风格，圆润可爱",
        "mature": f"，【人物风格】如有人物元素，使用成熟充气3D人物风格——充气膨胀质感但保持成人正常头身比，五官简洁不夸张，服装流行，整体饱满通透{_MATURE_BLOCK}",
    },
    # 风格9：粘土C4D
    9: {
        "child":  "，【人物风格】如有人物元素，使用粘土质感卡通人物风格，圆润萌感",
        "mature": f"，【人物风格】如有人物元素，使用成熟粘土C4D人物风格——粘土哑光质感但保持成人正常比例，五官简洁立体，服装有设计感，整体潮流活泼{_MATURE_BLOCK}",
    },
    # 风格10：潮流混合材质
    10: {
        "child":  "，【人物风格】如有人物元素，使用潮流卡通混合材质人物风格",
        "mature": f"，【人物风格】如有人物元素，使用成熟潮流混合材质人物风格——成人正常比例，材质感丰富（金属/玻璃/皮革），五官精致，整体艺术感强潮流感足{_MATURE_BLOCK}",
    },
}

STYLE_SUFFIX = {
    7:  ("，【主体物直接呈现——严格遵守】主体物直接置于画面中，无任何容器/面板/气泡/玻璃球/封闭形状包裹或衬托，主体物自然独立存在；玻璃质感体现在主体物自身材质上（折射/透明/高光边缘），背景保持干净简洁的同色系渐变，严禁添加任何包裹性/框架性玻璃形状；"
         "【人物禁止——最高优先级】严禁出现任何人物/人形/人体/人脸/手/肢体，画面中不得有任何人类形象，主视觉必须为产品/道具/物件/场景元素"),
    8:  "，【人物禁止——最高优先级】严禁出现任何人物/人形/人体/人脸/手/肢体，画面中不得有任何人类形象，主视觉必须为产品/道具/物件/场景元素",
    11: "，2D扁平插画矢量感，几何图形构成，低机位超广角仰视斜向动态构图，背景色块严格限制2-3个，单一视觉中心，现代品牌视觉",
    12: ("，2D矢量纯平涂现代扁平插画风格，"
         "【主体定位——最高优先级，严格遵守】"
         "所有主体元素必须聚合为一个整体视觉团，水平方向严格居中（画面中心线±10%以内），"
         "垂直方向位于画面中央偏上（30%-65%区间），整体视觉团占画面55-70%；"
         "若有2个主体，两者必须物理接触或重叠（间距为零），形成不可分割的单一视觉团，"
         "严禁将2个主体分放在画面左右两侧/上下两端，严禁任何主体元素漂离中心区域；"
         "【主体造型】白色或浅色大圆角造型，粗黑1.5-2.5pt等粗闭合轮廓线，无内部细节堆砌，平面切分硬边阴影（无羽化）；"
         "【描边规范】主体物及所有元素统一使用1.5-2.5pt等粗黑色闭合轮廓线，全画描边粗细一致，严禁粗细不一/虚线/无描边；"
         "【装饰元素】3-5个与应用内容相关的几何图标，使用背景同色系深浅变体细线描边，沿速度线/放射线方向向外发散，严禁密集堆砌或漂浮四角；"
         "【背景规范】背景为品牌主色纯色平涂，绝对干净，无任何纹理/图案/渐变覆盖背景；"
         "【人物规范】如有人物，必须使用Corporate Memphis风格——小头长肢巨型末端，点状眼极简弧线嘴，"
         "肤色米色/浅棕/橙棕（严禁绿/蓝/紫/灰等异常肤色），1.5-2.5pt黑色轮廓线，"
         "人物必须与主体物发生物理接触/重叠并有明确互动动作，约占内容区20%；"
         "若人物无法与主体形成自然和谐关联则省略人物"),
}


# ── 品牌色提取 ────────────────────────────────────

def _boost(r, g, b):
    """将颜色映射为高饱和(>0.82)高明度(>0.65)版本，拒绝灰暗褪色"""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    s = max(s, 0.82)
    v = max(v, 0.68)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
    return int(r2 * 255), int(g2 * 255), int(b2 * 255)


def _to_name(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hd = h * 360
    if s < 0.18:
        return "纯白" if v > 0.85 else "浅灰"
    if hd < 15 or hd >= 345:  return "鲜红"
    if hd < 40:                return "活力橙"
    if hd < 70:                return "明亮柠檬黄"
    if hd < 150:               return "荧光绿" if v > 0.65 else "翠绿"
    if hd < 195:               return "鲜艳青绿"
    if hd < 250:               return "电子蓝"
    if hd < 290:               return "星云紫"
    return "霓虹玫红"


def extract_brand_color(icon_url):
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(icon_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA").resize((64, 64), Image.LANCZOS)
        pixels = [
            (r, g, b) for r, g, b, a in img.getdata()
            if a > 100 and not (r > 240 and g > 240 and b > 240)
            and not (r < 20 and g < 20 and b < 20)
        ]
        if not pixels:
            return (0, 120, 255), "电子蓝"
        n = len(pixels)
        r = sum(p[0] for p in pixels) // n
        g = sum(p[1] for p in pixels) // n
        b = sum(p[2] for p in pixels) // n
        r, g, b = _boost(r, g, b)
        return (r, g, b), _to_name(r, g, b)
    except Exception as e:
        print(f"    ⚠ 颜色提取失败({e})，使用默认电子蓝")
        return (0, 120, 255), "电子蓝"


# ── 关键词提取 ────────────────────────────────────

STOPWORDS = {
    "的","了","是","在","有","和","与","或","等","及","为","到","您","用户","提供",
    "支持","功能","服务","使用","可以","通过","进行","我们","应用","手机","平台",
    "全国","亿万","领先","品牌","新版","升级","更新","快速","高效","安全","方便",
    "便捷","优质","专业","智能","免费","全面","丰富","海量","极速",
}

def extract_keywords(intro, n=5):
    import re
    text = re.sub(r"[\n\r【】\[\]「」（）《》<>、，。！？；：\s]+", " ", intro)
    words = re.findall(r"[一-鿿]{2,5}", text)
    seen, kw = set(), []
    for w in words:
        if w not in STOPWORDS and w not in seen:
            kw.append(w); seen.add(w)
        if len(kw) >= n:
            break
    return kw


# ── 主体推导 ─────────────────────────────────────

# 视觉无效词（过于抽象/功能描述/机构名，不可视化）
VISUAL_STOPWORDS = STOPWORDS | {
    "软件", "产品", "版本", "功能", "操作", "界面", "系统", "数据",
    "内容", "信息", "管理", "完成", "实现", "帮助", "一键", "全新",
    "独家", "超级", "更好", "体验", "随时", "随地", "轻松", "简单",
    "平台", "工具", "手机", "应用", "网络", "服务", "用户", "中国",
    "全球", "领先", "专属", "专业", "高效", "强大", "便捷", "优质",
    # 机构/品牌相关
    "安卓", "官方", "国家", "税务", "总局", "旗下", "推出", "字节",
    "跳动", "腾讯", "百度", "阿里", "华为", "小米", "官网", "集团",
    # 行为动词（不可视）
    "分享", "留住", "感动", "记录", "享受", "查看", "上传", "签到",
    "预订", "购买", "搜索", "查询", "发布", "提供", "支持", "满足",
}


def _extract_visual_words(text, n=4):
    """从文本提取可视化名词，过滤抽象/功能词"""
    import re
    if not text:
        return []
    text = re.sub(r'[\n\r【】\[\]「」（）《》<>、，。！？；：\s]+', ' ', text)
    words = re.findall(r'[一-鿿]{2,6}', text)
    seen, result = set(), []
    for w in words:
        if w not in VISUAL_STOPWORDS and w not in seen:
            result.append(w)
            seen.add(w)
        if len(result) >= n:
            break
    return result


def derive_subject(app_name, s_intro, tags, category, human_desc):
    """
    推导主视觉描述。优先级：
    1. S_INTRO → 提取2个具体可视化描述词组合
    2. NAME（分类）+ HUMAN_DESC → 根据分类场景提取标语
    3. SUBJECT_POOL 分类主体池兜底
    4. 通用兜底
    """
    import re

    LABEL_PATTERNS = {"安卓", "版本", "手机银行", "官方", "国家税务", "旗下", "APP", "app"}
    GENERIC_TAGS = {"常用工具", "其他工具", "休闲娱乐", "数字人", "安卓"}

    # ── 1. 优先从 S_INTRO 提取2个具体可视化描述 ──────────
    intro_kw = _extract_visual_words(s_intro, n=4) if s_intro else []
    concrete_intro = [w for w in intro_kw if w not in GENERIC_TAGS]

    if len(concrete_intro) >= 2:
        # 补充 HUMAN_DESC 作为场景氛围（≤20字，无标签）
        hd_clean = human_desc.strip() if human_desc else ""
        hd_hint = (
            hd_clean.strip("，。！~～")
            if hd_clean and len(hd_clean) <= 20
            and not any(p in hd_clean for p in LABEL_PATTERNS)
            else ""
        )
        subject = f"{concrete_intro[0]}与{concrete_intro[1]}"
        if hd_hint:
            subject += f"，{hd_hint}"
        return subject

    if len(concrete_intro) == 1:
        hd_clean = human_desc.strip() if human_desc else ""
        hd_hint = (
            hd_clean.strip("，。！~～")
            if hd_clean and len(hd_clean) <= 20
            and not any(p in hd_clean for p in LABEL_PATTERNS)
            else ""
        )
        if hd_hint:
            return f"{concrete_intro[0]}，{hd_hint}"
        return f"{concrete_intro[0]}，{app_name}产品场景"

    # ── 2. S_INTRO 不足时，根据 NAME 分类 + HUMAN_DESC ──
    hd_clean = human_desc.strip() if human_desc else ""
    hd_usable = (
        hd_clean.strip("，。！~～")
        if hd_clean and len(hd_clean) <= 24
        and not any(p in hd_clean for p in LABEL_PATTERNS)
        else ""
    )
    if hd_usable:
        return f"{hd_usable}，{app_name}产品场景"

    # ── 3. SUBJECT_POOL 分类主体池兜底 ────────────────
    pool = SUBJECT_POOL.get(category)
    if pool:
        return random.choice(pool)

    # ── 4. 通用兜底 ────────────────────────────────────
    return f"{app_name}核心功能视觉符号"


# ── Prompt 构建 ───────────────────────────────────

def build_prompt(app_name, color_name, style_idx,
                 s_intro="", tags="", category="", human_desc="", row_idx=0):
    idx, visual, color_rule_tpl, lighting, _ = STYLES[(style_idx - 1) % 12]

    # 随机选取点缀色色彩关系（补色/对比色/撞色/邻近对比色）
    accent_mode = random.choice(ACCENT_MODES)

    # 推导主视觉
    subject = derive_subject(app_name, s_intro, tags, category, human_desc)
    color_desc = color_rule_tpl.format(color=color_name)

    # 儿童类判断（人物风格、视觉成熟度、品牌层级豁免均会用到）
    is_children = any(kw in (category + app_name + tags) for kw in CHILDREN_KEYWORDS)

    # ── 孟菲斯风格走专属构图+氛围，其余走分类推荐/通用构图 ──
    if idx == 12:
        comp_desc = random.choice(MEMPHIS_COMPOSITIONS)
        atmo_desc = random.choice(MEMPHIS_ATMOSPHERES)
        prompt = (
            f"宽屏16:9横版应用商店封面图，{visual}，"
            f"主体视觉：{subject}，商业级品质，"
            f"色调：{color_desc}，"
            f"构图：{comp_desc}，"
            f"{atmo_desc}，"
            f"光线：{lighting}，"
            f"【画质要求】无任何文字Logo水印，高清画面清晰锐利，2D矢量扁平感，"
            f"色彩鲜活饱满，严禁复杂纹理、写实风格、3D渲染感、人物异常肤色"
        )
    else:
        # 分类驱动构图（未登记分类回退随机）
        comp_tuple, _ = pick_composition_for_category(category, row_idx, COMPOSITIONS)
        comp_name, comp_angle, comp_ratio = comp_tuple
        prompt = (
            f"宽屏16:9横版应用商店封面图，{visual}，"
            f"主体视觉：{subject}，商业级品质，"
            f"色调：{color_desc}，"
            f"构图：{comp_name}——{comp_angle}，{comp_ratio}，"
            f"光线：{lighting}，"
            f"【主体与背景对比——最高优先级】主体物主色明度必须与背景明度差值≥35%；"
            f"当主体与背景为同色相时，主体亮面必须使用高明度浅色（L 75-90%，接近奶白/米白带品牌色温度），"
            f"与背景形成跨明度强对比，同时用深色切面阴影（L 20-35%）增强主体立体感；"
            f"严禁主体物材质色与背景色过于接近导致融为一体，主体轮廓必须清晰可辨；"
            f"【点缀色调——光感融入】本次点缀色使用{accent_mode}，"
            f"点缀色总面积严格控制在画面的5%以内，仅作为光感层次点缀，禁止大面积铺开；"
            f"点缀色必须通过光的物理方式融入画面，而非作为独立漂浮元素出现；"
            f"融入方式：①主体边缘轮廓逆光（rim light）偏向点缀色色温，②发光屏幕/内发光的散射光晕带点缀色温，"
            f"③材质折射/玻璃色散/半透明透射产生点缀色光斑，④冷暖分色中阴影面渗入点缀色调；"
            f"点缀色强度柔和克制（S 45-65%），让画面色温丰富灵动，严禁以漂浮几何体/独立装饰形状呈现点缀色；"
            f"【背景约束】背景简洁克制，独立可辨识元素不超过3个，"
            f"禁止背景元素堆砌零散漂浮，禁止碎片化装饰物散落四周；"
            f"【画面充实度——最高优先级】严禁画面任何区域（顶部/左右/角落）出现大面积空旷留白，"
            f"主体及周边元素必须有效填充画面，确保视觉重心分布均匀，"
            f"顶部区域必须有背景层次元素（极度模糊的场景物件/光晕/流光装饰）填充，"
            f"不得呈现单调纯色大片空白，画面饱满度≥75%；"
            f"【禁用光效】严禁水波纹光效、老旧同心圆光晕、廉价粒子漫天散落、劣质彩虹折射纹、过度泛光Bloom，"
            f"【主体定位】主体视觉锚定画面垂直中心或偏上三分之一位置，严禁主体下沉至画面下半部造成顶部大面积空白，"
            f"主体重心保持在画面纵向35%-60%区间，主体需延伸占满画面高度的60%以上，"
            f"【画质要求】无任何文字Logo水印，高清画面清晰锐利，构图完整主次分明，精准对焦，正向情绪，"
            f"色彩鲜活饱满通透，严禁灰暗褪色低饱和颜色，严禁泥土色暗沉色，高级感克制简洁"
        )

    suffix = STYLE_SUFFIX.get(idx, "")

    # ── 气泡禁止约束（Style 7 除外） ──────────────────
    if idx != 7:
        suffix += "，【气泡禁止】严禁用气泡/玻璃球/圆形封闭容器/透明球体将主体物包裹在内部，主体物必须自然独立呈现，不被任何容器形状包围"

    # ── 屏幕UI简化约束（全局） ──────────────────────────
    suffix += ("，【屏幕UI约束】画面中如出现手机/电脑/平板屏幕，屏幕内界面必须极度简化"
               "——仅显示1-2个简洁图标/色块/符号，严禁出现复杂UI界面/密集图标行/文字列表/详细截图，"
               "屏幕内容一眼可辨，干净克制")

    # ── 人物约束 + 人物风格（合并处理，消除内部矛盾）──
    # 风格7/8 → 完全禁止人物（STYLE_SUFFIX 已注入），此处不追加
    # 风格11/12 → 人物允许且无正脸限制，按已有 SUFFIX 处理
    # 风格1-6/9-10：
    #   - 儿童类 → 注入皮克斯3D卡通人物风格（允许正脸大眼）
    #   - 非儿童 → 注入"优先无人物，如需则背影/侧身/局部"（严禁正脸）
    if idx not in [7, 8, 11, 12]:
        if is_children:
            if idx in _CHAR_STYLE:
                suffix += _CHAR_STYLE[idx]["child"]
            else:
                # 风格4 羊毛毡等没有专属儿童描述，用通用儿童卡通兜底
                suffix += ("，【人物风格】如有人物，使用皮克斯/迪士尼3D卡通风格——大眼有神、圆润可爱、"
                           "儿童化比例（头大身小）、表情生动活泼、亲切温暖，匹配儿童类产品调性")
        else:
            # 非儿童类：统一注入"优先无人物，需要则局部背影"约束
            suffix += ("，【人物约束——严格遵守】严禁人物成为画面主角，优先用产品/道具/场景替代人物；"
                       "如确需人物只能展示背影/侧身/局部（手/手臂/剪影），"
                       "严禁出现正脸/全脸/五官清晰的人物，严禁真实照片感人物，严禁卡通大眼萌系风格")

    global_light = (
        "，【全局光线】所有光源必须为大面积柔光漫射，严禁硬边光源、强烈锐利高光、生硬阴影边界，光影过渡必须平滑自然无明显分界线；"
        "【光源色彩——必须遵守】严禁使用中性白色光/纯白漫射光打光（白色光源使画面老旧廉价），"
        "所有主光/补光/环境光/轮廓光必须带有品牌色邻近色调的有色色温（偏暖橙/暖黄/冷青/冷紫均可，取决于品牌色），"
        "让整体光影与画面色调统一有层次感；"
        "丁达尔/天窗光效若出现，光束边缘必须完全扩散消融（如雾中光晕），严禁出现2条或多条清晰可见的硬边光线轮廓；"
        "【背景复杂度——必须遵守】严禁背景出现密集缠绕曲线/多条盘旋流光线/螺旋形装饰元素大量包裹主体，"
        "背景装饰元素总数不超过3个，保持画面简洁克制有呼吸感；"
        "【设备规范——必须遵守】画面中如出现手机/平板设备，必须使用无品牌特征的通用设备外观"
        "（简洁圆角矩形屏幕，无刘海/无灵动岛/无Home键/无苹果标志/无任何品牌Logo），"
        "严禁出现任何苹果iPhone/iPad外观特征"
    )

    # 全局追加：内容安全 + 视觉成熟度 + 品牌层级
    safety = SAFETY_CONSTRAINTS
    mature = "" if is_children else MATURE_CONSTRAINT
    tier = detect_brand_tier(app_name, s_intro, human_desc, is_children=is_children)
    tier_inject = TIER_INJECTION.get(tier, "")

    return prompt + suffix + global_light + safety + mature + tier_inject


# ── 图片压缩到 ≤ 200KB ────────────────────────────

def compress_to_limit(img_bytes, max_kb=MAX_KB):
    """将图片字节流压缩为 JPEG，确保 ≤ max_kb KB"""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    lo, hi, best = 10, 92, None
    while lo <= hi:
        mid = (lo + hi) // 2
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=mid, optimize=True)
        size_kb = buf.tell() / 1024
        if size_kb <= max_kb:
            best = buf.getvalue()
            lo = mid + 1
        else:
            hi = mid - 1
    # 若最低质量仍超限，缩小分辨率
    if best is None:
        w, h = img.size
        img = img.resize((w * 3 // 4, h * 3 // 4), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60, optimize=True)
        best = buf.getvalue()
    return best


# ── packy API 调用 ────────────────────────────────

def call_api(prompt):
    resp = requests.post(
        f"{PACKY_BASE}/images/generations",
        headers={
            "Authorization": f"Bearer {PACKY_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "prompt": prompt,
            "n": 1,
            "size": SIZE,
            "response_format": "b64_json",
        },
        timeout=180,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    item = resp.json()["data"][0]

    # b64_json 优先
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])

    # 回退：url
    if item.get("url"):
        ctx = ssl.create_default_context()
        req = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            return r.read()

    raise RuntimeError("响应中无可用图片数据")


# ── 主流程 ────────────────────────────────────────

def next_style_idx(current):
    """递增1-12循环，跳过母婴专用风格（索引4）"""
    idx = (current % 12) + 1
    while STYLES[(idx - 1) % 12][4] is not None:
        idx = (idx % 12) + 1
    return idx


def main():
    parser = argparse.ArgumentParser(
        description="批量生成应用商店封面图（基于 GPT-Image-2，自动按分类轮换 12 种风格）"
    )
    parser.add_argument("--start",  type=int, default=1,   help="CSV 起始行号（1-based，含）")
    parser.add_argument("--end",    type=int, default=20,  help="CSV 结束行号（1-based，含）")
    parser.add_argument("--style",  type=int, default=0,   help="强制使用指定风格编号 1-12（0=自动轮换；游戏类禁用 7/8/12 自动顺延）")
    parser.add_argument("--outdir", type=str, default="",  help=f"输出目录（默认：{OUT_DIR}）")
    parser.add_argument("--csv",    type=str, default="",  help=f"CSV 文件路径（默认：{CSV_PATH}）")
    args = parser.parse_args()

    # 惰性加载 API Key（环境变量优先，.env 兜底）
    global PACKY_KEY
    PACKY_KEY = _load_api_key()

    start_row, end_row = args.start, args.end
    force_style = args.style
    out_dir = args.outdir.strip() if args.outdir.strip() else OUT_DIR
    csv_path = args.csv.strip() if args.csv.strip() else CSV_PATH

    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"CSV 文件不存在：{csv_path}\n"
            f"请用 --csv /path/to/your.csv 指定，或将默认 CSV 放到 data/input.csv"
        )
    os.makedirs(out_dir, exist_ok=True)

    # 读 CSV（读取所有有效行，再按行号切片）
    print(f"📖 读取 CSV  行 {start_row}–{end_row}...")
    # 列名别名映射：支持中文带括号列名 → 标准英文键
    COL_ALIASES = {
        "PACKAGE_NAME": ["PACKAGE_NAME", "包名(PACKAGE_NAME)"],
        "APP_NAME":     ["APP_NAME", "应用名称(APP_NAME)"],
        "APP_LEVEL":    ["APP_LEVEL", "等级(APP_LEVEL)"],
        "S_INTRO":      ["S_INTRO", "简介(S_INTRO)"],
        "ICON_URL":     ["ICON_URL", "图标URL(ICON_URL)"],
        "HUMAN_DESC":   ["HUMAN_DESC", "描述(HUMAN_DESC)"],
        "NAME":         ["NAME", "分类(NAME)"],
        "TAGS":         ["TAGS"],
        "PARENT_ID":    ["PARENT_ID", "父分类ID(PARENT_ID)"],
    }

    def get_col(row, key, default=""):
        for alias in COL_ALIASES.get(key, [key]):
            if alias in row and row[alias]:
                return row[alias]
        return default

    all_rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if get_col(row, "ICON_URL").startswith("http"):
                all_rows.append(row)

    # 1-based → 0-based 切片
    rows = all_rows[start_row - 1 : end_row]
    total = len(rows)
    print(f"   取到 {total} 条有效记录（全量 {len(all_rows)} 条）\n")

    # 根据起始行号推导风格索引，保证全局轮换连续
    style_idx = 1
    while STYLES[(style_idx - 1) % 12][4] is not None:
        style_idx += 1
    # 跳过前 start_row-1 条已生成的风格轮换
    for _ in range(start_row - 1):
        style_idx = next_style_idx(style_idx)

    ok, fail = 0, 0

    for i, row in enumerate(rows, start_row):
        pkg        = get_col(row, "PACKAGE_NAME") or f"app{i}"
        name       = get_col(row, "APP_NAME") or pkg
        icon       = get_col(row, "ICON_URL")
        intro      = get_col(row, "S_INTRO")
        tags       = get_col(row, "TAGS")
        category   = get_col(row, "NAME")
        human_desc = get_col(row, "HUMAN_DESC")
        parent_id  = get_col(row, "PARENT_ID")
        is_game    = (parent_id == "游戏")

        print(f"{'─'*54}")
        print(f"[{i:02d}/{end_row}] {name}  ({pkg})")

        # 品牌色
        color_rgb, color_name = extract_brand_color(icon)
        print(f"   品牌色 → {color_name}  #{color_rgb[0]:02X}{color_rgb[1]:02X}{color_rgb[2]:02X}")

        # 主视觉推导预览
        subject_preview = derive_subject(name, intro, tags, category, human_desc)
        print(f"   主视觉 → {subject_preview}")

        # 风格选择优先级：
        #   ① --style N → 强制（游戏禁用自动顺延）
        #   ② 分类推荐命中 → 按推荐列表行号轮选（不前进 style_idx）
        #   ③ 全局轮换兜底（前进 style_idx）
        is_children_app = any(kw in (category + name + tags) for kw in CHILDREN_KEYWORDS)
        style_from_category = False

        if force_style > 0:
            cur_style = force_style
            if is_game and cur_style in GAME_BANNED_STYLES:
                tmp = next_style_idx(cur_style)
                while tmp in GAME_BANNED_STYLES:
                    tmp = next_style_idx(tmp)
                cur_style = tmp
            style_source = "强制指定"
        else:
            # 分类推荐（含母婴 [4,9,3,2] 多样化轮选）
            picked, from_cat = pick_style_for_category(
                category, fallback_style=style_idx, is_game=is_game, row_idx=i
            )
            cur_style = picked
            style_from_category = from_cat
            # 游戏类禁用顺延（仅在非分类推荐时才需要，分类推荐内部已过滤）
            if is_game and cur_style in GAME_BANNED_STYLES:
                while cur_style in GAME_BANNED_STYLES:
                    cur_style = next_style_idx(cur_style)
                style_source = "全局轮换(游戏禁用顺延)"
            elif from_cat:
                style_source = f"分类推荐 {CATEGORY_RECOMMENDED_STYLES.get(category)}"
            else:
                style_source = "全局轮换(分类无推荐)"

        s = STYLES[(cur_style - 1) % 12]
        # 品牌层级识别
        tier = detect_brand_tier(name, intro, human_desc, is_children=is_children_app)
        tier_label = {"premium": "高端", "quality": "精品", "standard": "标准"}.get(tier, "标准")

        print(f"   风格   → #{cur_style} {s[1]}  [{style_source}]")
        print(f"   分类   → {category}  PARENT={parent_id}  TAGS={tags}")
        print(f"   层级   → {tier_label}  |  儿童类: {'是' if is_children_app else '否'}")

        # Prompt
        prompt = build_prompt(name, color_name, cur_style,
                              s_intro=intro, tags=tags,
                              category=category, human_desc=human_desc,
                              row_idx=i)
        print(f"   Prompt → {prompt[:120]}...")

        # 生图（强制风格时加前缀，避免覆盖正式文件）
        prefix = f"style{force_style}_" if force_style > 0 else ""
        out_path = os.path.join(out_dir, f"{prefix}{pkg}.jpg")
        try:
            img_bytes = call_api(prompt)
            jpeg_bytes = compress_to_limit(img_bytes)
            size_kb = len(jpeg_bytes) / 1024
            with open(out_path, "wb") as f:
                f.write(jpeg_bytes)
            print(f"   ✅ 已保存  {out_path}  ({size_kb:.0f} KB)")
            ok += 1
        except Exception as e:
            print(f"   ❌ 失败: {e}")
            fail += 1

        # 仅在使用"全局轮换兜底"时前进 style_idx
        # （强制指定 / 分类推荐 → 不前进，保持序列连续性）
        used_fallback = (
            force_style == 0
            and not is_children_app
            and not style_from_category
        )
        if used_fallback:
            style_idx = next_style_idx(style_idx)

        if i < end_row:
            time.sleep(0.5)

    print(f"\n{'='*54}")
    print(f"🎉 完成！成功 {ok} 张，失败 {fail} 张")
    print(f"   输出目录: {out_dir}")


if __name__ == "__main__":
    main()
