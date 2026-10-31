"""Atomic comic documents and project-owned content-addressed assets."""
from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .comic import validate, recompute
from .run_repository import RunRepository
from .visual_presets import validate_reference_bytes


class RevisionConflict(ValueError):
    pass


class ComicRepository(RunRepository):
    def pipeline_path(self, run_id):
        return self.run_dir(run_id) / 'comic.json'

    def load(self, run_id, *, required=True):
        with self._lock_for(run_id):
            path = self.pipeline_path(run_id)
            if not path.exists():
                raise FileNotFoundError('漫画工程不存在')
            return json.loads(path.read_text(encoding='utf-8'))

    def save(self, run_id, payload, *, render=False):
        with self._lock_for(run_id):
            validate(payload)
            self.validate_assets(run_id, payload)
            recompute(payload)
            archive = payload.setdefault('panel_archive', {})
            if self.pipeline_path(run_id).exists():
                for page in self.load(run_id)['pages']:
                    for panel in page['panels']:
                        if panel.get('image_versions') or panel.get('generation_request'):
                            archive[panel['id']] = deepcopy(panel)
            def text_snapshot(value):
                snapshot = deepcopy({k:v for k,v in value.items() if k not in {'history','revision','panel_archive'}})
                for page in snapshot['pages']:
                    for panel in page['panels']:
                        for key in ('image_versions','current_image','generation_request','generation_error'):
                            panel.pop(key,None)
                return snapshot
            if self.pipeline_path(run_id).exists():
                before = text_snapshot(self.load(run_id))
                after = text_snapshot(payload)
                if before != after:
                    history = payload.setdefault('history',[])
                    if not history or history[-1] != before:
                        history.append(before)
                    del history[:-50]
            payload['revision'] = int(payload.get('revision', 0)) + 1
            self._atomic_write_json(self.pipeline_path(run_id), payload)
        return self.pipeline_path(run_id)

    @contextmanager
    def transaction(self, run_id, *, render=False):
        with self._lock_for(run_id):
            project = self.load(run_id)
            yield project
            self.save(run_id, project)

    def list_projects(self):
        result = []
        for path in self.root.glob('*/comic.json'):
            try:
                data = self.load(path.parent.name)
                result.append(dict(id=data['id'],title=data['title'],revision=data['revision'],pages=len(data['pages']),modified_at=path.stat().st_mtime))
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda p:p['modified_at'], reverse=True)

    def asset(self, project_id, path):
        if not isinstance(path, str) or '\\' in path or not path.startswith('assets/'):
            raise ValueError('素材路径必须位于工程 assets 目录')
        root = self.run_dir(project_id)
        candidate = (root / path).resolve()
        assets = (root / 'assets').resolve()
        if assets not in candidate.parents or candidate.is_symlink():
            raise ValueError('非法素材路径')
        if not candidate.is_file():
            raise ValueError(f'工程素材缺失：{path}')
        return candidate

    def add_asset(self, project_id, filename, data, content_type=None):
        suffix = validate_reference_bytes(filename, data, content_type)
        relative = 'assets/' + hashlib.sha256(data).hexdigest() + suffix
        path = self.run_dir(project_id) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return relative

    def validate_assets(self, project_id, document):
        from .comic_render import referenced_assets
        for path in referenced_assets(document):
            self.asset(project_id,path)

    def replace(self, project_id, incoming):
        with self.transaction(project_id) as old:
            if incoming.get('revision') != old['revision']:
                raise RevisionConflict('工程已被其他操作更新，请重新加载后重试')
            if incoming.get('id') != project_id:
                raise ValueError('不能更改工程 ID')
            candidate = deepcopy(incoming)
            from .comic import normalize_characters
            candidate['characters'] = normalize_characters(candidate.get('characters', []))
            # Client saves cannot forge or erase generation provenance.
            old_panels = {p['id']:p for page in old['pages'] for p in page['panels']}
            for page in candidate['pages']:
                for panel in page['panels']:
                    original = old_panels.get(panel['id'])
                    if original:
                        panel['image_versions'] = deepcopy(original.get('image_versions',[]))
                        if panel.get('current_image') not in {v['path'] for v in panel['image_versions']} | {None}:
                            raise ValueError('只能激活已有图片版本')
                        for key in ('generation_request','generation_error','generation_status'):
                            if key in original:
                                panel[key] = deepcopy(original[key])
            candidate['history'] = deepcopy(old.get('history',[]))
            candidate['panel_archive'] = deepcopy(old.get('panel_archive',{}))
            old.clear()
            old.update(candidate)
        return self.load(project_id)
