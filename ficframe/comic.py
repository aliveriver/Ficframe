"""Comic document rules. No illustration prompt rules or HTTP dependencies."""
from __future__ import annotations

import math
import json
import re
from copy import deepcopy
from uuid import uuid4
from typing import Any

from .source_reference import build_novel_source_ref, build_description_source_ref, resolve_source_ref

SCHEMA_VERSION = 1
MODES = {'inherit', 'text', 'blank', 'clean'}
PANEL_SHAPES = {'rectangle', 'rounded', 'circle', 'diamond', 'hexagon'}
SCRIPT_FIELDS = ('description', 'characters', 'actions', 'expression', 'camera', 'angle', 'scene_id', 'time', 'source_ref', 'balloons')


def uid(prefix: str) -> str:
    return f'{prefix}_{uuid4().hex}'


def panels(project):
    return [panel for page in project['pages'] for panel in page['panels']]


def detect_characters(text, characters):
    """Match character names and aliases in a panel's source text."""
    haystack = str(text or '')
    matches = []
    for card in characters or []:
        names = [card.get('name', ''), *(card.get('aliases') or [])]
        if any(name and name in haystack for name in names):
            matches.append(card.get('id'))
    return [value for value in matches if value]


def panel_by_id(project, panel_id):
    return next(panel for panel in panels(project) if panel['id'] == panel_id)


def new_panel(description=''):
    return dict(id=uid('panel'), description=description, characters=[], actions='', expression='', camera='中景',
                angle='平视', scene_id='', time='', source_ref=build_description_source_ref(description),
                positive_prompt='', negative_prompt='', rect=dict(x=.04, y=.04, w=.92, h=.92),
                shape='rectangle', crop=dict(x=.5, y=.5, zoom=1), lettering_mode='inherit', locks={}, state_bindings={},
                effective_states={}, needs_review=[], balloons=[], image_versions=[], current_image=None)


def new_page():
    return dict(id=uid('page'), width=1200, height=1700, gutter=16, lettering_mode='inherit', panels=[])


def template(page, kind='auto'):
    count = len(page['panels'])
    target_count = 6 if str(kind) in {'six', '6'} else 3 if str(kind) in {'three', '3', 'grid-3'} else 4
    if str(kind) in {'four','4','three','3','grid-3','six','6','top','top-large'} and count < target_count:
        page['panels'].extend(new_panel() for _ in range(target_count-count))
        count = target_count
    if not count:
        return
    columns = 2
    rows = math.ceil(count / columns)
    for index, panel in enumerate(page['panels']):
        if panel.get('locks', {}).get('layout'):
            continue
        columns = 1 if count == 1 else 3 if str(kind) in {'three', '3', 'grid-3'} else 2
        rows = math.ceil(count / columns)
        if str(kind) in {'top', 'top-large'} and count > 1:
            if index == 0:
                rect = dict(x=.03, y=.03, w=.94, h=.44)
            else:
                lower_rows = math.ceil((count - 1) / 2)
                rect = dict(x=.03 + ((index - 1) % 2) * .47, y=.5 + ((index - 1) // 2) * .47 / lower_rows,
                            w=.47, h=.47 / lower_rows)
        elif str(kind) in {'feature-left', 'hero-left'} and count > 1:
            if index == 0:
                rect = dict(x=.03, y=.03, w=.57, h=.94)
            else:
                small_count = count - 1
                rect = dict(x=.63, y=.03 + ((index - 1) * .94 / small_count), w=.34, h=.94 / small_count - .02)
        else:
            rect = dict(x=.03 + (index % columns) * .94 / columns, y=.03 + (index // columns) * .94 / rows,
                        w=.94 / columns, h=.94 / rows)
        panel['rect'] = rect


def normalize_characters(characters):
    result = deepcopy(characters)
    for card in result:
        card.setdefault('id', uid('char'))
        # Old identity prompts can contain baseline clothing. Require an explicit
        # identity-only fragment instead of guessing which words are garments.
        card.setdefault('identity_core', ', '.join(card.get('fixed_traits') or card.get('visual_traits') or []) or card.get('identity_prompt', ''))
        card.setdefault('states', [])
        if not card['states']:
            variable = card.get('variable_states') or {}
            for item in card.get('appearance_states') or []:
                label = item.get('label', '外貌状态')
                card['states'].append(dict(id=uid('state'), label=label,
                                           outfit=item.get('prompt', ''), props=item.get('props', ''), injuries=item.get('injuries', ''),
                                           confirmed=label.lower() in {'default', '默认', '基础状态'} or not card['states']))
            if variable:
                card['states'].insert(0, dict(id=uid('state'), label='资料默认状态', outfit=variable.get('outfit', ''),
                                             props=variable.get('props', ''), injuries=variable.get('injuries', ''), confirmed=True))
    return result


def new_project(title='', source_text='', characters=None):
    project = dict(schema_version=1, id=uid('comic'), revision=0, title=title or '未命名漫画',
                   source_text=source_text.replace('\r\n', '\n'), characters=normalize_characters(characters or []),
                   style={}, scenes=[], lettering_mode='text', text_settings=dict(dialogue=True, narration=True, sfx=True),
                   pages=[new_page()], history=[])
    project['pages'][0]['panels'] = [new_panel()]
    return project


def validate(project):
    if project.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('不支持的漫画工程数据版本')
    ids = set()
    def unique(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value) or value in ids:
            raise ValueError('工程包含非法或重复 ID')
        ids.add(value)
    unique(project['id'])
    if project.get('lettering_mode') not in MODES - {'inherit'}:
        raise ValueError('工程嵌字模式无效')
    for card in project['characters']:
        unique(card['id'])
        for state in card.get('states', []):
            unique(state['id'])
    for scene in project.get('scenes', []):
        unique(scene['id'])
    for page in project['pages']:
        unique(page['id'])
        for key in ('width', 'height'):
            if not isinstance(page[key], (int, float)) or not 100 <= page[key] <= 8192:
                raise ValueError('页尺寸必须在 100–8192 像素之间')
        if page['width'] * page['height'] > 32_000_000:
            raise ValueError('单页不能超过 3200 万像素')
        if not 0 <= page.get('gutter', 16) <= 200:
            raise ValueError('格间距无效')
        for item in [page, *page['panels']]:
            if item.get('lettering_mode', 'inherit') not in MODES:
                raise ValueError('嵌字模式无效')
        for panel in page['panels']:
            unique(panel['id'])
            panel['shape'] = panel.get('shape', 'rectangle')
            if panel['shape'] not in PANEL_SHAPES:
                raise ValueError('画格形状无效')
            reference = panel.get('source_ref')
            if isinstance(reference,str):
                reference = {'kind':'novel','quote':reference}
            panel['source_ref'] = resolve_source_ref(project['source_text'], reference)
            scene_id = panel.get('scene_id')
            if scene_id and scene_id not in {s['id'] for s in project.get('scenes',[])}:
                raise ValueError('画格绑定的场景不存在')
            for item in [panel, *panel.get('balloons', [])]:
                if item is not panel:
                    unique(item['id'])
                rect = item['rect']
                if any(not isinstance(rect.get(k), (int, float)) or not math.isfinite(rect[k]) for k in ('x','y','w','h')):
                    raise ValueError('矩形坐标无效')
                if rect['x'] < 0 or rect['y'] < 0 or rect['w'] <= 0 or rect['h'] <= 0 or rect['x'] + rect['w'] > 1.001 or rect['y'] + rect['h'] > 1.001:
                    raise ValueError('矩形必须位于页面或画格内部')


def recompute(project):
    cards = {card['id']: card for card in project['characters']}
    current = {}
    issues = []
    for panel in panels(project):
        previous = panel.get('effective_states', {})
        effective = {}
        review = []
        for character_id in panel.get('characters', []):
            card = cards.get(character_id)
            if not card:
                issues.append(dict(panel_id=panel['id'], severity='error', message='无效角色绑定'))
                continue
            binding = panel.get('state_bindings', {}).get(character_id)
            if binding:
                state = next((s for s in card.get('states', []) if s['id'] == binding.get('state_id')), None)
                if binding.get('scope','continue') not in {'panel','continue'}:
                    issues.append(dict(panel_id=panel['id'],severity='error',message='状态适用范围无效'))
                    continue
                if not state:
                    issues.append(dict(panel_id=panel['id'], severity='error', message=f"{card['name']}：无效外貌状态"))
                    review.append('无效外貌状态')
                    continue
                entry = dict(state=deepcopy(state), source_panel=panel['id'], scope=binding.get('scope','continue'),
                             confirmed=bool(binding.get('confirmed') and state.get('confirmed')))
                if binding.get('overrides'):
                    entry['state'].update({k:v for k,v in binding['overrides'].items() if k in ('outfit','props','injuries')})
                if entry['scope'] == 'continue':
                    current[character_id] = deepcopy(entry)
            elif character_id in current:
                entry = deepcopy(current[character_id])
            else:
                defaults = [s for s in card.get('states', []) if s.get('confirmed')]
                if defaults:
                    entry = dict(state=deepcopy(defaults[0]), source_panel='character_default', scope='continue', confirmed=True)
                    current[character_id] = deepcopy(entry)
                else:
                    issues.append(dict(panel_id=panel['id'], severity='error', message=f"{card['name']}：缺少已确认外貌状态"))
                    review.append('缺少外貌状态')
                    continue
            if not entry['confirmed']:
                issues.append(dict(panel_id=panel['id'], severity='suggestion', message=f"{card['name']}：状态建议需要确认"))
                review.append('状态需要确认')
            effective[character_id] = entry
            if card.get('identity_prompt') and not card.get('identity_core'):
                issues.append(dict(panel_id=panel['id'], severity='suggestion', message=f"{card['name']}：请确认不含默认服饰的固定身份描述"))
        if previous and previous != effective:
            review.append('连续性变化，请检查已有 Prompt 和图片')
            if panel.get('locks', {}).get('state'):
                effective = previous
                review.append('状态已锁定，保留原快照')
        if panel.get('locks', {}).get('state') and previous:
            effective = previous
            for character_id, entry in effective.items():
                if entry.get('scope') == 'continue':
                    current[character_id] = deepcopy(entry)
        panel['effective_states'] = effective
        panel['needs_review'] = list(dict.fromkeys([*panel.get('needs_review', []), *review]))
        for note in panel['needs_review']:
            issues.append(dict(panel_id=panel['id'], severity='warning', message=note))
    return issues


def operation(project, request):
    action = request['action']
    page = next((p for p in project['pages'] if p['id'] == request.get('page_id')), None)
    if action == 'add_page':
        project['pages'].append(new_page())
    elif action == 'delete_page':
        if any(any(p.get('locks', {}).values()) for p in page['panels']):
            raise ValueError('页面含有锁定画格，请先解锁')
        project['pages'].remove(page)
    elif action == 'move_page':
        project['pages'].remove(page)
        project['pages'].insert(max(0, int(request.get('index', 0))), page)
    elif action == 'add_panel':
        page['panels'].append(new_panel())
        template(page)
    elif action == 'set_panel_count':
        try:
            target_count = int(request.get('count', 0))
        except (TypeError, ValueError) as exc:
            raise ValueError('本页画格数必须是整数') from exc
        if not 1 <= target_count <= 100:
            raise ValueError('本页画格数必须在 1–100 之间')
        locked_count = sum(bool(panel.get('locks', {}).get('layout')) for panel in page['panels'])
        if target_count < locked_count:
            raise ValueError(f'本页有 {locked_count} 个布局锁定画格，无法减少到 {target_count} 格')
        while len(page['panels']) < target_count:
            page['panels'].append(new_panel())
        if len(page['panels']) > target_count:
            removable = [panel for panel in reversed(page['panels']) if not panel.get('locks', {}).get('layout')]
            remove_count = len(page['panels']) - target_count
            removed = set(id(panel) for panel in removable[:remove_count])
            page['panels'] = [panel for panel in page['panels'] if id(panel) not in removed]
        layout_kind = request.get('template', 'auto')
        template(page, layout_kind if layout_kind in {'top', 'top-large', 'feature-left', 'hero-left'} else 'auto')
    elif action == 'template':
        template(page, request.get('template', 'four'))
    else:
        panel = panel_by_id(project, request['panel_id'])
        origin = next(p for p in project['pages'] if panel in p['panels'])
        if any(panel.get('locks', {}).values()):
            raise ValueError('请先解除画格锁定再进行结构编辑')
        if action == 'use_candidate':
            path = request.get('path')
            candidates = {c['path'] for c in project.get('candidate_images',[])}
            if path not in candidates:
                raise ValueError('候选素材不存在')
            panel['image_versions'].append(dict(id=uid('version'),path=path,snapshot={'strategy':'imported-candidate'}))
            panel['current_image'] = path
        elif action == 'delete_panel':
            origin['panels'].remove(panel)
        elif action == 'split_panel':
            clone = deepcopy(panel)
            clone.update(id=uid('panel'), image_versions=[], current_image=None)
            for balloon in clone['balloons']:
                balloon['id'] = uid('balloon')
            rect = panel['rect']
            rect['w'] /= 2
            clone['rect'] = dict(rect, x=rect['x'] + rect['w'])
            origin['panels'].insert(origin['panels'].index(panel)+1, clone)
        elif action == 'merge_panels':
            other = panel_by_id(project, request['other_panel_id'])
            if other is panel or any(other.get('locks', {}).values()):
                raise ValueError('不能合并该画格')
            panel['description'] += '\n' + other['description']
            panel['characters'] = list(dict.fromkeys(panel['characters'] + other['characters']))
            panel['balloons'].extend(other['balloons'])
            panel['image_versions'].extend(other['image_versions'])
            panel.setdefault('merged_sources', []).append(other['source_ref'])
            panel.setdefault('merged_panels', []).append(deepcopy(other))
            panel['needs_review'].append('合并画格，请确认角色状态与构图')
            next(p for p in project['pages'] if other in p['panels'])['panels'].remove(other)
        elif action == 'move_panel':
            destination = next(p for p in project['pages'] if p['id'] == request.get('target_page_id', origin['id']))
            origin['panels'].remove(panel)
            destination['panels'].insert(max(0, int(request.get('index', 0))), panel)
        else:
            raise ValueError('未知漫画编辑操作')
    recompute(project)


COMIC_SYSTEM = '''You are a comic script editor. Return JSON only. Plan sequential comic pages and rectangular panels, reading order, pacing, actions, shots, dialogue with speakers and narration. Each panel is one moment; the entire project is a multi-page comic. Generate clean panel art, with separate program-rendered balloons and text. Never request the image model to draw Chinese dialogue. Do not apply novel illustration rules. Do not invent costume changes: propose states only with source evidence and require confirmation. Respect locks and user edits. Source quotes must be verbatim; never present paraphrase as source. Character identity and variable costume/props/injuries are separate.'''


def build_prompt(project, panel):
    cards = {c['id']:c for c in project['characters']}
    fragments = [panel.get('description',''), panel.get('actions',''), panel.get('expression',''),
                 panel.get('camera',''), panel.get('angle',''), panel.get('time','')]
    scene = next((s for s in project.get('scenes',[]) if s['id'] == panel.get('scene_id')), {})
    fragments.append(scene.get('description',''))
    negative = []
    for character_id in panel['characters']:
        card = cards.get(character_id, {})
        entry = panel.get('effective_states', {}).get(character_id, {})
        state = entry.get('state', {})
        fragments.append(f"{card.get('name','')}: fixed identity: {card.get('identity_core','')}; current visible state: " + '; '.join(str(state.get(k,'')) for k in ('outfit','props','injuries')))
        if card.get('negative_identity_core'):
            negative.append(card['negative_identity_core'])
    style = project.get('style', {})
    if style.get('reference_mode', 'text') == 'text':
        fragments.append(str(style.get('positive_prompt') or style.get('positive') or style.get('summary') or ''))
        negative.append(str(style.get('negative_prompt') or style.get('negative') or ''))
    return '\n'.join(f for f in fragments if f), ', '.join(f for f in negative if f)


def final_prompt(project, panel):
    base, negative = build_prompt(project, panel)
    mode = panel.get('lettering_mode', 'inherit')
    page = next(p for p in project['pages'] if panel in p['panels'])
    if mode == 'inherit':
        mode = page.get('lettering_mode', 'inherit')
    if mode == 'inherit':
        mode = project['lettering_mode']
    prompt = '\n'.join([panel.get('positive_prompt') or base, base,
        'Comic panel art: one continuous scene, one simultaneous moment. Generate clean artwork only. Page borders, balloons and lettering are rendered separately by the application.'])
    if mode != 'clean' and panel.get('balloons'):
        prompt += '\nReserve quiet negative space for these later lettering regions: ' + str([b['rect'] for b in panel['balloons']])
    return prompt, ', '.join(filter(None, [panel.get('negative_prompt'), negative, 'rendered dialogue, speech balloons, captions, page borders, panel collage, watermark']))


def plan_script(project, page_count, per_page, instructions='', provider=None):
    if page_count < 1 or per_page < 1:
        raise ValueError('页数与每页格数必须大于零')
    if page_count * per_page > 2000:
        raise ValueError('单次规划最多 2000 格，可分次增加页面；工程无固定页数上限')
    existing = panels(project)
    if provider:
        payload = dict(source_text=project['source_text'], characters=project['characters'], scenes=project['scenes'],
                       pages=page_count, panels_per_page=per_page, instructions=instructions,
                       current_panels=existing, required_schema={'pages':[{'panels':[{'description':'','quote':'verbatim source or empty',
                       'characters':['character id'], 'actions':'', 'expression':'','camera':'','angle':'','scene_id':'','time':'',
                       'balloons':[{'kind':'dialogue','speaker':'character id','text':''}]}]}]})
        data = json.loads(provider.text(COMIC_SYSTEM, json.dumps(payload, ensure_ascii=False), purpose='comic:script'))
        proposed = data.get('pages')
        if not isinstance(proposed, list) or not proposed or not all(isinstance(p.get('panels'), list) for p in proposed):
            raise ValueError('漫画脚本返回格式无效')
    else:
        text = project['source_text']
        proposed = []
        total = page_count * per_page
        for page_index in range(page_count):
            items = []
            for index in range(per_page):
                position = page_index * per_page + index
                start = int(len(text)*position/total)
                end = int(len(text)*(position+1)/total)
                items.append(dict(description=text[start:end], source_start=start, source_end=end))
            proposed.append(dict(panels=items))
    for pi, proposal in enumerate(proposed):
        if pi >= len(project['pages']):
            project['pages'].append(new_page())
        page = project['pages'][pi]
        for index, candidate in enumerate(proposal['panels']):
            if index >= len(page['panels']):
                page['panels'].append(new_panel())
            panel = page['panels'][index]
            if panel.get('locks',{}).get('script'):
                continue
            for key in SCRIPT_FIELDS:
                if key in candidate and key not in {'source_ref','balloons'}:
                    panel[key] = deepcopy(candidate[key])
            cards_by_id = {card['id']: card for card in project.get('characters', [])}
            cards_by_name = {card.get('name'): card for card in project.get('characters', [])}
            requested_characters = candidate.get('characters')
            if isinstance(requested_characters, list):
                resolved = []
                for value in requested_characters:
                    card = cards_by_id.get(value) or cards_by_name.get(value)
                    if card and card['id'] not in resolved:
                        resolved.append(card['id'])
                panel['characters'] = resolved
            if not panel.get('characters'):
                panel['characters'] = detect_characters(panel.get('description', ''), project.get('characters', []))
            if 'balloons' in candidate:
                panel['balloons'] = [dict(id=uid('balloon'), kind=b.get('kind','dialogue'), speaker=b.get('speaker',''),
                    text=b.get('text',''), rect=dict(x=.06,y=min(.1+i*.2,.7),w=.8,h=.18), font_size=28,
                    line_spacing=1.3, writing_mode='horizontal', tail=dict(x=.5,y=.5), show=True)
                    for i,b in enumerate(candidate['balloons'])]
            quote = candidate.get('quote','')
            if provider:
                panel['source_ref'] = resolve_source_ref(project['source_text'], dict(kind='novel',quote=quote)) if quote else build_description_source_ref(panel['description'])
            elif candidate['source_start'] < candidate['source_end']:
                panel['source_ref'] = build_novel_source_ref(project['source_text'],candidate['source_start'],candidate['source_end'])
        template(page)
    # Remove superseded unlocked script from the active reading order. The
    # repository history and panel archive retain its text and image versions.
    kept_pages = []
    for pi, page in enumerate(project['pages']):
        planned_count = len(proposed[pi]['panels']) if pi < len(proposed) else 0
        page['panels'] = [p for index,p in enumerate(page['panels']) if index < planned_count or any(p.get('locks',{}).values())]
        if pi < len(proposed) or page['panels']:
            kept_pages.append(page)
    project['pages'] = kept_pages
    recompute(project)
    for panel in panels(project):
        if not panel.get('locks',{}).get('prompt'):
            panel['positive_prompt'], panel['negative_prompt'] = build_prompt(project,panel)
    return project
