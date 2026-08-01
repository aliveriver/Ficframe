from __future__ import annotations


DEFAULT_STYLE = {
    "name": "cinematic light-novel illustration",
    "medium": "high quality anime light novel illustration, cinematic composition",
    "palette": "warm laboratory lamplight, soft silver highlights, restrained teal and amber accents",
    "lighting": "soft volumetric light, gentle rim light, natural skin tones",
    "line": "clean detailed linework, subtle painterly texture",
    "continuity_rules": [
        "保持同一角色的发色、发型、脸型、身高比例和固定标志物",
        "只有剧情明确变化时才改变服装、伤痕、血迹和道具",
        "相邻画面保持一致的光线方向、环境材质和人物年龄感",
        "不要增加剧情没有出现的新角色或夸张武器",
    ],
    "negative_prompt": (
        "low quality, worst quality, blurry, extra fingers, missing fingers, malformed hands, "
        "bad anatomy, duplicate face, inconsistent character design, wrong outfit, extra people, "
        "text, watermark, logo, overexposed, underexposed"
    ),
}
