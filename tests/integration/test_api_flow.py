from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_passwordless_end_to_end_flow(tmp_path: Path) -> None:
    script = r'''
import io, json, zipfile
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    assert client.get('/health/live').status_code == 200
    nested_page = client.get('/recommendations')
    assert nested_page.status_code == 200 and 'text/html' in nested_page.headers['content-type']
    assert client.get('/api/resumes').status_code == 401
    session = client.post('/api/auth/local-session')
    assert session.status_code == 200, session.text
    csrf = session.json()['csrf_token']
    headers = {'X-CSRF-Token': csrf}
    llm_config = client.patch('/api/settings/llm', headers=headers, json={
        'llm_base_url':'https://api.example.invalid/v1', 'llm_api_key':'fictional-api-key',
        'llm_model':'fictional-model', 'llm_input_price_rmb_per_million':1,
        'llm_output_price_rmb_per_million':2, 'llm_monthly_budget_rmb':75
    })
    assert llm_config.status_code == 200, llm_config.text
    assert llm_config.json()['api_key_configured'] is True
    assert 'fictional-api-key' not in llm_config.text
    assert llm_config.json()['api_keys'][0]['masked'].endswith('-key')
    added_key = client.post('/api/settings/llm/keys', headers=headers, json={
        'label':'备用 Key','api_key':'fictional-backup-key'
    })
    assert added_key.status_code == 200 and 'fictional-backup-key' not in added_key.text
    new_key_id = next(item['id'] for item in added_key.json()['api_keys'] if item['label'] == '备用 Key')
    assert added_key.json()['active_api_key_id'] == 'legacy'
    assert next(item for item in added_key.json()['api_keys'] if item['id'] == new_key_id)['label'] == '备用 Key'
    selected_key = client.post(f'/api/settings/llm/keys/{new_key_id}/activate', headers=headers)
    assert selected_key.status_code == 200 and selected_key.json()['active_api_key_id'] == new_key_id
    switched_key = client.post('/api/settings/llm/keys/legacy/activate', headers=headers)
    assert switched_key.status_code == 200 and switched_key.json()['active_api_key_id'] == 'legacy'
    removed_key = client.delete(f'/api/settings/llm/keys/{new_key_id}', headers=headers)
    assert removed_key.status_code == 200 and len(removed_key.json()['api_keys']) == 1
    persisted_llm = client.get('/api/settings/llm')
    assert persisted_llm.json()['llm_model'] == 'fictional-model'
    assert 'fictional-api-key' not in persisted_llm.text
    provider = client.patch('/api/settings/preferences', headers=headers, json={'llm_provider':'disabled'})
    assert provider.status_code == 200 and provider.json()['effective_llm_provider'] == 'disabled'
    assert client.post('/api/jobs/import', json={
        'company':'虚构科技','title':'无 CSRF 岗位','description':'这条写请求必须被拒绝',
        'url':'https://example.invalid/jobs/no-csrf'
    }).status_code == 403
    invalid = client.post('/api/jobs/import', headers=headers, json={
        'company':'虚构科技','title':'无效岗位','description':'SECRET_JD_TOO_SHORT',
        'url':'not-a-url'
    })
    assert invalid.status_code == 422
    assert invalid.json()['code'] == 'VALIDATION_ERROR'
    assert 'SECRET_JD_TOO_SHORT' not in invalid.text and 'input' not in invalid.text

    resume_text = '# 简历\n李雷\n邮箱：fictional@example.com\n电话：13900000000\n## 项目经历\n- 使用 Python 和 RAG 构建课程项目，准确率提升 12%\n'
    upload = client.post('/api/resumes', headers=headers, files={'file':('fictional.md', resume_text.encode(), 'text/markdown')})
    assert upload.status_code == 200, upload.text
    facts = upload.json()['facts']
    assert facts and 'fictional@example.com' not in json.dumps(upload.json(), ensure_ascii=False)
    fact_id = next(item['fact_id'] for item in facts if 'Python' in item['redacted_text'])
    assert client.post('/api/profile/confirm', headers=headers).status_code == 200
    revised_text = '使用 Python 和 RAG 构建虚构课程项目，准确率提升 12%'
    revised = client.post(f'/api/facts/{fact_id}', headers=headers, json={
        'action':'revise','text':revised_text
    })
    assert revised.status_code == 200, revised.text
    revised_fact_id = revised.json()['fact_id']
    assert revised_fact_id != fact_id and revised.json()['supersedes_fact_id'] == fact_id
    assert client.get('/api/profile').json()['confirmed'] is False
    assert client.post('/api/profile/confirm', headers=headers).status_code == 200
    fact_id = revised_fact_id

    job = client.post('/api/jobs/import', headers=headers, json={
        'company':'虚构科技','title':'RAG 后端开发工程师','description':'面向 2027 届校园招聘，使用 Python 开发大模型 RAG 平台并负责安全测试。',
        'url':'https://example.invalid/jobs/graduate-1','location':'北京','recruitment_type':'校园招聘','graduation_year':'2027'
    })
    assert job.status_code == 200, job.text
    job_id = job.json()['id']
    suitability = client.post(f'/api/jobs/{job_id}/feedback', headers=headers, json={'action':'suitable'})
    assert suitability.status_code == 200 and suitability.json()['suitability'] == 'suitable'
    evaluation = client.get('/api/evaluation')
    assert evaluation.status_code == 200 and evaluation.json()['labels'] == 1
    assert evaluation.json()['precision_at_10'] is None
    recompute = client.post('/api/recommendations/recompute', headers=headers)
    assert recompute.status_code == 200, recompute.text
    assert recompute.json()['llm_status'].startswith('disabled:')
    recommendations = client.get('/api/recommendations').json()['items']
    assert recommendations and recommendations[0]['job_id'] == job_id
    assert recommendations[0]['job']['title'] == 'RAG 后端开发工程师'
    assert client.get('/api/tailor-advice').json() == []
    generated_advice = client.post(f'/api/jobs/{job_id}/tailor-advice', headers=headers)
    assert generated_advice.status_code == 200, generated_advice.text
    assert generated_advice.json()['suggestions'][0]['suggested_text']
    advice_list = client.get('/api/tailor-advice')
    assert advice_list.status_code == 200 and advice_list.json()[0]['job']['id'] == job_id

    sentence = revised_text
    tailored = client.post(f'/api/jobs/{job_id}/tailor', headers=headers, json={
        'confirmed': True, 'sentences':[{'text': sentence, 'fact_ids':[fact_id]}]
    })
    assert tailored.status_code == 200, tailored.text
    assert tailored.json()['validation_result']['valid'] is True
    assert tailored.json()['status'] == 'completed', tailored.text
    assert tailored.json()['validation_result']['pdf']['valid'] is True

    csv_text = '公司名,投递渠道,岗位,岗位类型,业务线/部门,链接,Base地,投递日期,状态,当前阶段,阶段结果,当前进度更新时间,内推码,联系人/内推人,面试时间,结果,备注\n虚构科技,官网,RAG 后端开发工程师,校招,AI平台,https://example.invalid/jobs/graduate-1,北京,2026-08-04,已投递,投递,待处理,,,,,,\n'
    preview = client.post('/api/applications/import-csv?commit=false', headers=headers, files={'file':('applications.csv', csv_text.encode(), 'text/csv')})
    assert preview.status_code == 200 and preview.json()['valid'] is True
    committed = client.post('/api/applications/import-csv?commit=true', headers=headers, files={'file':('applications.csv', csv_text.encode(), 'text/csv')})
    assert committed.json()['committed'] == 1
    exported = client.get('/api/applications/export-csv')
    assert exported.status_code == 200 and '虚构科技' in exported.content.decode('utf-8-sig')

    backup = client.post('/api/backups', headers=headers)
    assert backup.status_code == 200, backup.text
    backup_id = backup.json()['backup_id']
    archive = client.get(f'/api/backups/{backup_id}/download')
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        exported_settings = bundle.read('config/settings.json').decode()
        assert 'fictional-api-key' not in exported_settings and 'llm_api_key' not in exported_settings
    restored = client.post('/api/restore', headers=headers, files={'file':('backup.zip', archive.content, 'application/zip')})
    assert restored.status_code == 200, restored.text
    assert restored.json()['restored_counts']['candidate_profiles'] == 1
    assert client.post('/api/auth/logout', headers=headers).status_code == 200
    print(json.dumps({'job_id':job_id,'fact_id':fact_id,'tailor_status':tailored.json()['status']}))
'''
    env = os.environ.copy()
    env.update(
        {
            "APP_SECRET": "integration-secret",
            "ADMIN_PASSWORD": "integration-password",
            "DATABASE_URL": f"sqlite:///{tmp_path / 'integration.db'}",
            "DATA_DIR": str(tmp_path / "data"),
            "MODEL_CACHE_DIR": str(tmp_path / "models"),
            "LLM_PROVIDER": "disabled",
            "PYTHONPATH": str(Path(__file__).parents[2] / "backend"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["job_id"] == 1
    assert summary["fact_id"].startswith("fact_")
    assert summary["tailor_status"] == "completed"
