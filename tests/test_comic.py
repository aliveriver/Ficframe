from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ficframe.comic import (new_project, new_panel, new_page, panels, plan_script, operation, recompute,
                            build_prompt, final_prompt, validate)
from ficframe.comic_repository import ComicRepository, RevisionConflict
from ficframe.comic_workflow import generate, rebuild_prompts
from ficframe.providers import ProviderError


def fixture():
    project = new_project('跨页换装', '小林说：“走吧。”\n小雨点头。\n小林换上雨衣，走进雨中。', [
        dict(id='lin',name='小林',fixed_traits=['black hair'],identity_prompt='black hair, white coat',
             negative_identity_prompt='wrong outfit',states=[dict(id='coat',label='外套',outfit='white coat',props='bag',injuries='',confirmed=True),
             dict(id='rain',label='雨衣',outfit='yellow raincoat',props='umbrella',injuries='',confirmed=True)]),
        dict(id='yu',name='小雨',fixed_traits=['short hair'],states=[dict(id='yu_default',label='默认',outfit='blue jacket',props='',injuries='',confirmed=True)])])
    project['pages'] = [new_page(),new_page()]
    for page in project['pages']:
        page['panels'] = [new_panel(),new_panel()]
        for panel in page['panels']:
            panel['characters'] = ['lin','yu']
    panels(project)[2]['state_bindings'] = {'lin':dict(state_id='rain',scope='continue',confirmed=True)}
    recompute(project)
    return project


class ComicRulesTests(unittest.TestCase):
    def test_cross_page_state_and_reorder(self):
        project = fixture()
        p = panels(project)
        self.assertEqual(p[1]['effective_states']['lin']['state']['id'],'coat')
        self.assertEqual(p[3]['effective_states']['lin']['state']['id'],'rain')
        operation(project,dict(action='move_panel',panel_id=p[2]['id'],target_page_id=project['pages'][0]['id'],index=0))
        self.assertEqual(p[0]['effective_states']['lin']['state']['id'],'rain')
        self.assertTrue(p[0]['needs_review'])

    def test_locked_state_stays_and_change_warns(self):
        project = fixture()
        p = panels(project)
        p[3]['locks']['state'] = True
        p[2]['state_bindings']['lin']['state_id'] = 'coat'
        recompute(project)
        self.assertEqual(p[3]['effective_states']['lin']['state']['id'],'rain')
        self.assertIn('状态已锁定，保留原快照',p[3]['needs_review'])

    def test_locked_middle_node_propagates_actual_snapshot(self):
        project = fixture()
        p = panels(project)
        p[2]['locks']['state'] = True
        p[2]['state_bindings']['lin']['state_id'] = 'coat'
        recompute(project)
        self.assertEqual(p[2]['effective_states']['lin']['state']['id'],'rain')
        self.assertEqual(p[3]['effective_states']['lin']['state']['id'],'rain')

    def test_smaller_replanning_removes_superseded_script(self):
        project = new_project(source_text='一二三四五六七八九十')
        plan_script(project,4,4)
        plan_script(project,1,1)
        self.assertEqual(len(project['pages']),1)
        self.assertEqual(len(panels(project)),1)

    def test_comic_prompt_excludes_old_outfit_identity(self):
        project = fixture()
        panel = panels(project)[3]
        panel['positive_prompt'],panel['negative_prompt'] = build_prompt(project,panel)
        positive,negative = final_prompt(project,panel)
        self.assertIn('yellow raincoat',positive)
        self.assertNotIn('white coat',positive)
        self.assertNotIn('wrong outfit',negative)
        self.assertNotIn('No panel grid',positive)
        self.assertIn('Comic panel art',positive)

    def test_template_preserves_content_images_and_locks(self):
        project = fixture()
        panel = panels(project)[0]
        panel['description'] = '用户剧情'
        panel['balloons'] = [dict(id='bubble',text='走吧',rect=dict(x=.1,y=.1,w=.5,h=.2))]
        panel['current_image'] = 'assets/test.png'
        panel['locks']['layout'] = True
        before = copy.deepcopy(panel)
        operation(project,dict(action='template',page_id=project['pages'][0]['id'],template='six'))
        self.assertEqual(panel,before)

    def test_planning_and_rebuilding_respect_locks(self):
        project = fixture()
        panel = panels(project)[0]
        panel['description'] = '手工锁定剧情'
        panel['positive_prompt'] = '手工锁定Prompt'
        panel['locks'].update(script=True,prompt=True)
        plan_script(project,4,4,provider=None)
        rebuild_prompts(project,[p['id'] for p in panels(project)])
        self.assertEqual(panel['description'],'手工锁定剧情')
        self.assertEqual(panel['positive_prompt'],'手工锁定Prompt')
        self.assertEqual(len(project['pages']),4)
        validate(project)

    def test_model_quotes_are_verified(self):
        project = fixture()
        class LLM:
            def text(self,system,user,**kwargs):
                self_test.assertIn('comic',system)
                self_test.assertNotIn('SINGLE_FRAME',system)
                return json.dumps({'pages':[{'panels':[{'description':'改写','quote':'模型编造的原文','characters':['lin']}]}]})
        self_test = self
        plan_script(project,1,1,provider=LLM())
        self.assertEqual(panels(project)[0]['source_ref']['status'],'unresolved')

    def test_invalid_state_is_error_unconfirmed_is_suggestion(self):
        project = fixture()
        panel = panels(project)[0]
        panel['state_bindings']['lin'] = dict(state_id='absent',confirmed=True)
        issues = recompute(project)
        self.assertTrue(any(i['severity']=='error' for i in issues))
        panel['state_bindings']['lin'] = dict(state_id='coat',confirmed=False)
        self.assertTrue(any(i['severity']=='suggestion' for i in recompute(project)))

    def test_split_and_merge_keep_original_images(self):
        project = fixture()
        first = panels(project)[0]
        first['current_image'] = 'assets/test.png'
        operation(project,dict(action='split_panel',panel_id=first['id']))
        split = panels(project)[1]
        self.assertEqual(first['current_image'],'assets/test.png')
        self.assertIsNone(split['current_image'])
        operation(project,dict(action='merge_panels',panel_id=first['id'],other_panel_id=split['id']))
        self.assertEqual(first['current_image'],'assets/test.png')
        self.assertTrue(first['merged_panels'])


class ComicPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = ComicRepository(self.temp.name)
        self.project = fixture()
        self.repo.save(self.project['id'],self.project)

    def tearDown(self):
        self.temp.cleanup()

    def test_atomic_revision_and_restore(self):
        project = self.repo.load(self.project['id'])
        project['title'] = '恢复编辑'
        saved = self.repo.replace(project['id'],project)
        self.assertEqual(saved['title'],'恢复编辑')
        with self.assertRaises(RevisionConflict):
            self.repo.replace(project['id'],project)

    def test_asset_paths_cannot_escape(self):
        for path in ('../secret','assets/../../secret','C:/secret','assets\\secret'):
            with self.assertRaises(ValueError):
                self.repo.asset(self.project['id'],path)

    def test_generation_only_selected_and_retry_snapshot(self):
        from PIL import Image
        class Provider:
            config = SimpleNamespace(image=SimpleNamespace(provider='openai',base_url='https://example.invalid',model='mock'))
            calls = []
            def image(self,prompt,target,**kwargs):
                self.calls.append((prompt,copy.deepcopy(kwargs)))
                if len(self.calls) == 1:
                    raise ProviderError('mock failure')
                Image.new('RGB',(64,64),'blue').save(target)
        class Reporter:
            def update(self,*args): pass
            def log(self,*args): pass
        provider = Provider()
        before = self.repo.load(self.project['id'])
        selected = panels(before)[0]
        generate(self.repo,before['id'],provider,[selected['id']],'1024x1024',1,Reporter())
        after = self.repo.load(before['id'])
        self.assertEqual(provider.calls[0][0],provider.calls[1][0])
        self.assertEqual(provider.calls[0][1]['negative_prompt'],provider.calls[1][1]['negative_prompt'])
        for old,new in zip(panels(before)[1:],panels(after)[1:]):
            self.assertEqual(old,new)
        self.assertEqual(len(panels(after)[0]['image_versions']),1)
        self.assertEqual(panels(after)[0]['image_versions'][0]['snapshot']['strategy'],'comic-panel-v1')
        edited = copy.deepcopy(after)
        edited['lettering_mode'] = 'clean'
        edited['pages'][0]['panels'][0]['description'] = '修改剧情'
        self.repo.replace(edited['id'],edited)
        self.assertEqual(len(provider.calls),2)

    def test_siliconflow_identity_reference_is_not_silently_dropped(self):
        from PIL import Image
        buffer = __import__('io').BytesIO()
        Image.new('RGB',(10,10)).save(buffer,format='PNG')
        path = self.repo.add_asset(self.project['id'],'identity.png',buffer.getvalue())
        with self.repo.transaction(self.project['id']) as project:
            project['characters'][0]['reference_images'] = [path]
        class Provider:
            config = SimpleNamespace(image=SimpleNamespace(provider='siliconflow',base_url='https://example.invalid',model='mock'))
            def image(self,*args,**kwargs):
                raise AssertionError('Unsupported reference must not reach provider')
        class Reporter:
            def update(self,*args): pass
        with self.assertRaisesRegex(ValueError,'不支持角色参考'):
            generate(self.repo,self.project['id'],Provider(),[panels(self.project)[0]['id']],'1024x1024',0,Reporter())
        self.assertEqual(panels(self.repo.load(self.project['id']))[0]['generation_status'],'failed')

    def test_unsupported_scene_reference_is_clear(self):
        from PIL import Image
        buffer = __import__('io').BytesIO()
        Image.new('RGB',(10,10)).save(buffer,format='PNG')
        path = self.repo.add_asset(self.project['id'],'scene.png',buffer.getvalue())
        with self.repo.transaction(self.project['id']) as project:
            project['scenes'] = [dict(id='scene',description='雨中',reference_images=[path])]
            panels(project)[0]['scene_id'] = 'scene'
        class Provider:
            config = SimpleNamespace(image=SimpleNamespace(provider='comfyui',base_url='http://localhost',model='mock'))
            def image(self,*args,**kwargs):
                raise AssertionError('Unsupported reference must not call image API')
        class Reporter:
            def update(self,*args): pass
        with self.assertRaisesRegex(ValueError,'不支持独立场景'):
            generate(self.repo,self.project['id'],Provider(),[panels(self.project)[0]['id']],'1024x1024',0,Reporter())


if __name__ == '__main__':
    unittest.main()
