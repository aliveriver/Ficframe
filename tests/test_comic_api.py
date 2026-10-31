import copy
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from ficframe import api


class ComicAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(api,'RUNS',Path(self.temp.name)/'web-runs')
        self.patch.start()
        api.RUNS.mkdir()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def create(self):
        response = self.client.post('/api/comics',json={'title':'双人对话','source_text':'小林走进教室。小雨说：“早上好。”'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_save_restore_layout_text_modes_export_import(self):
        project = self.create()
        project_id = project['id']
        root = f'/api/comics/{project_id}'
        image = io.BytesIO()
        Image.new('RGB',(400,300),'#3399aa').save(image,format='PNG')
        upload = self.client.post(root+'/assets',files={'file':('test.png',image.getvalue(),'image/png')})
        self.assertEqual(upload.status_code,200,upload.text)
        path = upload.json()['path']
        project['candidate_images'] = [{'path':path,'title':'候选'}]
        panel = project['pages'][0]['panels'][0]
        panel['balloons'] = [dict(id='balloon_one',kind='dialogue',speaker='小雨',text='早上好。今天一起出发吧！',
            rect=dict(x=.1,y=.1,w=.7,h=.25),font_size=32,line_spacing=1.3,writing_mode='vertical',tail=dict(x=.5,y=.5),show=True)]
        response = self.client.put(root,json=project)
        self.assertEqual(response.status_code,200,response.text)
        project = response.json()
        self.assertEqual(self.client.put(root,json=project|{'revision':0}).status_code,409)
        page_id = project['pages'][0]['id']
        versions = []
        for mode in ('text','blank','clean'):
            project['lettering_mode'] = mode
            response = self.client.put(root,json=project)
            self.assertEqual(response.status_code,200,response.text)
            project = response.json()
            preview = self.client.get(root+f'/preview/{page_id}')
            self.assertEqual(preview.status_code,200,preview.text[:100] if preview.status_code!=200 else '')
            self.assertEqual(Image.open(io.BytesIO(preview.content)).size,(1200,1700))
            versions.append(preview.content)
        self.assertNotEqual(versions[0],versions[1])
        self.assertNotEqual(versions[1],versions[2])
        for format in ('png','pdf','strip','project'):
            export = self.client.get(root+'/export',params={'format':format,'mode':'text'})
            self.assertEqual(export.status_code,200,export.text[:100] if export.status_code!=200 else '')
            self.assertGreater(len(export.content),100)
            if format == 'project':
                imported = self.client.post('/api/comics/import',files={'file':('comic.zip',export.content,'application/zip')})
                self.assertEqual(imported.status_code,200,imported.text)
                restored = imported.json()
                self.assertNotEqual(restored['id'],project_id)
                self.assertEqual(restored['pages'][0]['panels'][0]['balloons'],project['pages'][0]['panels'][0]['balloons'])
                self.assertEqual(self.client.get(f"/api/comics/{restored['id']}/assets/{path}").status_code,200)
        self.assertEqual(self.client.get(root+'/check').status_code,200)

    def test_local_planning_task_and_manual_operations(self):
        project = self.create()
        root = '/api/comics/'+project['id']
        response = self.client.post(root+'/plan-task',json={'pages':4,'panels_per_page':4,'use_llm':False})
        self.assertEqual(response.status_code,202,response.text)
        for _ in range(200):
            tasks = self.client.get(root+'/tasks').json()['tasks']
            task = next(t for t in tasks if t['task_id']==response.json()['task_id'])
            if task['status'] in ('succeeded','failed'):
                break
            time.sleep(.01)
        self.assertEqual(task['status'],'succeeded',task)
        project = self.client.get(root).json()
        self.assertEqual(len(project['pages']),4)
        first = project['pages'][0]['panels'][0]
        response = self.client.post(root+'/operation',json={'action':'move_panel','panel_id':first['id'],
            'target_page_id':project['pages'][3]['id'],'index':0})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['pages'][3]['panels'][0]['id'],first['id'])

    def test_create_from_novel_is_independent(self):
        repo = api.get_run_repository()
        run_id = 'source'
        repo.run_dir(run_id).mkdir()
        repo.novel_path(run_id).write_text('原小说正文',encoding='utf-8')
        repo.save(run_id,{'characters':[{'name':'小林','fixed_traits':['黑发'],'reference_images':[]}],'shots':[]},render=False)
        original = repo.pipeline_path(run_id).read_bytes()
        response = self.client.post('/api/comics',json={'source_run_id':run_id,'title':'独立漫画'})
        self.assertEqual(response.status_code,200,response.text)
        project = response.json()
        self.assertEqual(project['source_text'],'原小说正文')
        project['source_text'] = '编辑漫画原文'
        self.assertEqual(self.client.put('/api/comics/'+project['id'],json=project).status_code,200)
        self.assertEqual(repo.pipeline_path(run_id).read_bytes(),original)
        self.assertEqual(repo.novel_path(run_id).read_text(encoding='utf-8'),'原小说正文')

    def test_history_restores_script_without_erasing_images(self):
        project = self.create()
        root = '/api/comics/'+project['id']
        project['pages'][0]['panels'][0]['description'] = '第一版剧情'
        project = self.client.put(root,json=project).json()
        project['pages'][0]['panels'][0]['description'] = '第二版剧情'
        project = self.client.put(root,json=project).json()
        self.assertTrue(project['history'])
        index = next(i for i,h in enumerate(project['history']) if h['pages'][0]['panels'][0]['description']=='第一版剧情')
        response = self.client.post(root+'/restore',json={'index':index})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['pages'][0]['panels'][0]['description'],'第一版剧情')

    def test_deleted_panel_history_retains_image_versions(self):
        project = self.create()
        root = '/api/comics/'+project['id']
        image = io.BytesIO()
        Image.new('RGB',(20,20),'red').save(image,format='PNG')
        path = self.client.post(root+'/assets',files={'file':('candidate.png',image.getvalue(),'image/png')}).json()['path']
        project['candidate_images'] = [{'path':path,'title':'素材'}]
        project = self.client.put(root,json=project).json()
        panel_id = project['pages'][0]['panels'][0]['id']
        project = self.client.post(root+'/operation',json={'action':'use_candidate','panel_id':panel_id,'path':path}).json()
        project = self.client.post(root+'/operation',json={'action':'delete_panel','panel_id':panel_id}).json()
        index = len(project['history'])-1
        restored = self.client.post(root+'/restore',json={'index':index})
        self.assertEqual(restored.status_code,200,restored.text)
        panel = restored.json()['pages'][0]['panels'][0]
        self.assertEqual(panel['current_image'],path)
        self.assertEqual(len(panel['image_versions']),1)

    def test_interrupted_generation_can_retry_original_request(self):
        from types import SimpleNamespace
        project = self.create()
        root = '/api/comics/'+project['id']
        path = Path(self.temp.name)/'comics'/project['id']/'comic.json'
        project['pages'][0]['panels'][0].update(generation_status='running',generation_request={'strategy':'comic-panel-v1','positive_prompt':'PINNED',
            'negative_prompt':'original','size':'1024x1024','states':{},'style':{},'scene':{},'identity_groups':[],
            'style_references':[],'scene_references':[],'reference_roles':[]})
        path.write_text(__import__('json').dumps(project),encoding='utf-8')
        class Provider:
            config = SimpleNamespace(image=SimpleNamespace(provider='openai',base_url='https://example.invalid',model='mock'))
            def image(self,prompt,target,**kwargs):
                assert prompt == 'PINNED'
                Image.new('RGB',(20,20),'green').save(target)
        with patch.object(api,'OpenAICompatibleProvider',Provider):
            response = self.client.post(root+'/generate-task',json={'mode':'failed'})
            self.assertEqual(response.status_code,202,response.text)
            for _ in range(200):
                tasks = self.client.get(root+'/tasks').json()['tasks']
                task = next(t for t in tasks if t['task_id']==response.json()['task_id'])
                if task['status'] in ('succeeded','failed'): break
                time.sleep(.01)
            self.assertEqual(task['status'],'succeeded',task)
        restored = self.client.get(root).json()
        self.assertEqual(restored['pages'][0]['panels'][0]['image_versions'][0]['snapshot']['positive_prompt'],'PINNED')

    def test_invalid_asset_and_archive_fail_clearly(self):
        project = self.create()
        root = '/api/comics/'+project['id']
        self.assertEqual(self.client.post(root+'/assets',files={'file':('bad.png',b'bad','image/png')}).status_code,400)
        project['pages'][0]['panels'][0]['current_image'] = '../../secret.png'
        self.assertEqual(self.client.put(root,json=project).status_code,400)
        self.assertEqual(self.client.post('/api/comics/import',files={'file':('bad.zip',b'bad','application/zip')}).status_code,400)


if __name__ == '__main__':
    unittest.main()
