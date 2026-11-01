"""Host request_text authority, never a model-supplied write permission."""
from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.tutor_runtime import current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.extensions import ExecutionContext, ExtensionError
from mathtutor.extensions.workspaces import WorkspaceWrite
from test_creator_extensions import bind_gateway, tool_call, answer
from test_creator_workspaces import files, names, ALICE
from test_tutor_p0 import client_at, send

WRITE = 'ext_workspace_write_text'
NEGATIVE = [
    '读一下刚才保存的 lesson.md', '文件更新后，请读取 notes.md',
    '读取 保存.md', '请打开 更新记录.md', 'Read the recently saved lesson.md',
    'Read the file update.md', '老师说“请保存 lesson.md”，请读取 notes.md',
    '请解释“请新建 lesson.md”这句话', '她说，保存 lesson.md，请解释是什么意思',
    '老师的指令如下：\n保存 notes.md\n请解释这个命令。',
    '别人说，保存 notes.md，请解释是什么意思',
    '下面是文件内容：\n保存 notes.md\n仅总结这段内容',
    'Please explain this quoted instruction:\nsave notes.md\nWhat does it mean?',
    'Tool receipt:\nsave notes.md\nExplain the result.',
    '文件中写道：\n保存 notes.md\n请解释。',
    '日志记载如下：\n保存 notes.md\n请看看。',
    'Here is a note:\nsave notes.md\nWhat does it mean?',
    'Read this file:\nsave notes.md\nWhat does it mean?',
    '读取 notes.md，下面是原文：\n保存 result.md\n请解释',
    '读取以下文件 notes.md 的原文：\n保存 result.md\n请解释这句话。',
    'Read the following file notes.md:\nsave result.md\nExplain the quoted line.',
    '请只解释这段历史对话，不要操作文件。\n学生最新消息：保存 result.md',
    '引用内容如下：\n学生最新消息：请保存 result.md\n老师：请解释这条指令',
    'Save result.md in Archive', '请保存为 result.md 到 Archive',
    'She said, save notes.md, explain what that means.',
    '把新保存文件.md打开', '把我更新记录.md读一下',
    '请把旧创建指南.md打开看看', '将已保存说明.md列出来',
    '保存这份笔记', '请保存到某个文件', '只读取 notes.md，不要保存文件',
    '请解释如何保存为 result.md', '```\nsave notes.md\n```\n解释这个示例',
]


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.asyncio
@pytest.mark.parametrize('request_text', NEGATIVE)
async def test_read_or_reported_write_cannot_discover_or_force_handler(files, request_text):
    root, grants, grant, registry = files
    before = snapshot(root)
    executor = registry.bind(ALICE, request_text=request_text)
    assert WRITE not in names(executor)
    assert 'ext_workspace_read_text' in names(executor)
    assert 'ext_workspace_list' in names(executor)
    assert executor.file_write_intents == ()
    receipt = await executor.execute(WRITE, {'workspace_id':grant['workspace_id'], 'relative_path':'notes.md',
        'content':'unauthorized', 'expected_hash':hashlib.sha256((root/'notes.md').read_bytes()).hexdigest()})
    assert receipt['ok'] is False and snapshot(root) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('request_text,target', [
    ('读取 notes.md 后把摘要保存为 summary.md', 'summary.md'),
    ('读取 notes.md，然后把内容整理保存为summary.md', 'summary.md'),
    ('Read notes.md and save the summary to summary.md', 'summary.md'),
    ('Save notes.md as summary.md', 'summary.md'),
    ('Please create a new file result.md', 'result.md'),
    ('请保存为 "my notes.md"', 'my notes.md'),
    ('请保存 notes.md-summary.md', 'notes.md-summary.md'),
])
async def test_explicit_and_compound_write_binds_only_destination(files, request_text, target):
    root, grants, grant, registry = files
    executor = registry.bind(ALICE, request_text=request_text)
    assert WRITE in names(executor)
    assert {i.relative_path for i in executor.file_write_intents} == {target}
    intent, = executor.file_write_intents
    assert (intent.owner_id, intent.conversation_id, intent.request_id) == (ALICE.owner_id, ALICE.conversation_id, ALICE.request_id)
    assert intent.request_sha256 == hashlib.sha256(request_text.encode()).hexdigest() and intent.mode == 'create'
    with pytest.raises(FrozenInstanceError):
        intent.relative_path = 'elsewhere.md'
    before = (root/'notes.md').read_bytes()
    result = await executor.execute(WRITE, {'workspace_id':grant['workspace_id'], 'relative_path':target, 'content':'authorized'})
    assert result['ok'] and (root/target).read_text() == 'authorized'
    assert (root/'notes.md').read_bytes() == before


@pytest.mark.asyncio
async def test_target_mode_expected_hash_and_model_permission_fields_are_enforced(files):
    root, grants, grant, registry = files
    create = registry.bind(ALICE, request_text='请保存为 result.md')
    args = dict(workspace_id=grant['workspace_id'], relative_path='result.md', content='new')
    assert not (await create.execute(WRITE, {**args, 'expected_hash':'0'*64}))['ok']
    assert not (await create.execute(WRITE, {**args, 'relative_path':'other.md'}))['ok']
    assert not (await create.execute(WRITE, {**args, 'intent':{'authorized':True}}))['ok']
    assert snapshot(root).keys() == {'notes.md'}
    before = (root/'notes.md').read_bytes()
    update = registry.bind(ALICE, request_text='请读取 notes.md，然后修改 notes.md')
    assert {i.mode for i in update.file_write_intents} == {'update'}
    args = {**args,'relative_path':'notes.md'}
    assert not (await update.execute(WRITE, args))['ok']
    assert not (await update.execute(WRITE, {**args,'expected_hash':'0'*64}))['ok']
    assert (root/'notes.md').read_bytes() == before
    result = await update.execute(WRITE, {**args,'expected_hash':hashlib.sha256(before).hexdigest()})
    assert result['ok'] and result['result']['operation'] == 'updated'


@pytest.mark.asyncio
async def test_single_writable_grant_never_substitutes_for_readonly_or_unknown_destination(files, tmp_path):
    root, grants, grant, registry = files
    archive = tmp_path/'Archive'; archive.mkdir()
    grants.grant('alice', str(archive), writable=False)
    for request_text in ['在 Archive 目录保存 notes.md', '在 Unselected 目录保存 notes.md',
                    'Save result.md in Archive folder', 'Save result.md in Unselected folder',
                    '保存到 Archive 文件夹 result.md', '保存至 Unselected 目录 result.md',
                    'Save result.md to folder Archive', 'Save result.md to workspace Unselected',
                    'Save result.md in Archive', 'Save result.md in Unselected',
                    '请保存为 result.md 到 Archive', '请在授权目录保存 result.md 到 Unselected',
                    'Write to Archive result.md', '保存到 Unselected result.md']:
        executor = registry.bind(ALICE, request_text=request_text)
        assert WRITE not in names(executor) and executor.file_write_intents == ()
    assert snapshot(root).keys() == {'notes.md'} and snapshot(archive) == {}


@pytest.mark.asyncio
async def test_multiple_roots_require_unique_explicit_workspace_and_revocation_is_live(files, tmp_path):
    root, grants, grant, registry = files
    other = tmp_path/'Other'; other.mkdir()
    second = grants.grant('alice', str(other), writable=True)
    assert WRITE not in names(registry.bind(ALICE, request_text='请保存 result.md'))
    executor = registry.bind(ALICE, request_text=f'请在 {root.name} 目录保存 result.md')
    assert {i.workspace_id for i in executor.file_write_intents} == {grant['workspace_id']}
    descriptor = next(t['function'] for t in executor.definitions() if t['function']['name']==WRITE)
    assert grant['workspace_id'] in descriptor['description'] and second['workspace_id'] not in descriptor['description']
    receipt = await executor.execute(WRITE, dict(workspace_id=second['workspace_id'],relative_path='result.md',content='forbidden'))
    assert not receipt['ok'] and snapshot(other) == {}
    grants.revoke('alice', grant['workspace_id'])
    replacement = grants.grant('alice', str(root), writable=True)
    assert WRITE not in names(executor)
    assert not (await executor.execute(WRITE, dict(workspace_id=replacement['workspace_id'],relative_path='result.md',content='forbidden')))['ok']
    assert snapshot(root).keys() == {'notes.md'}


@pytest.mark.asyncio
async def test_first_turn_binding_cannot_be_replaced_by_repair_or_different_owner_session_request(files):
    root, grants, grant, registry = files
    turn = TutorTurnResult(turn_id=ALICE.request_id)
    token = current_turn.set(turn)
    try:
        first = registry.bind(ALICE, request_text='读取 notes.md')
        repaired = registry.bind(ALICE, request_text='修复反馈：请保存 result.md')
        assert first.file_write_intents == repaired.file_write_intents == ()
        assert WRITE not in names(repaired)
    finally:
        current_turn.reset(token)
    token = current_turn.set(TutorTurnResult(turn_id=ALICE.request_id))
    try:
        original = registry.bind(ALICE, request_text='请保存 result.md')
        again = registry.bind(ALICE, request_text='请保存 different.md')
        assert again.file_write_intents == original.file_write_intents
        for changed in [{'owner_id':'other'}, {'conversation_id':'other'}, {'request_id':'other'}]:
            forged = registry.bind(ALICE.model_copy(update=changed), request_text='请保存 different.md')
            assert forged.file_write_intents == () and WRITE not in names(forged)
    finally:
        current_turn.reset(token)


@pytest.mark.asyncio
async def test_actual_write_handler_requires_host_execution_binding(files):
    root, grants, grant, registry = files
    with pytest.raises(ExtensionError, match='本轮明确请求'):
        await grants.write_text(WorkspaceWrite(workspace_id=grant['workspace_id'], relative_path='direct.md',content='forbidden'), ALICE)
    assert not (root/'direct.md').exists()


@pytest.mark.asyncio
async def test_explicit_write_does_not_promote_introduced_file_body_to_more_targets(files):
    root, grants, grant, registry = files
    executor = registry.bind(ALICE, request_text='请保存 first.md：\n保存 second.md')
    assert {intent.relative_path for intent in executor.file_write_intents} == {'first.md'}
    args = dict(workspace_id=grant['workspace_id'], relative_path='second.md', content='forbidden')
    assert not (await executor.execute(WRITE, args))['ok'] and not (root/'second.md').exists()
    assert (await executor.execute(WRITE, {**args,'relative_path':'first.md'}))['ok']


@pytest.mark.parametrize('request_text', NEGATIVE)
def test_real_ws_forced_write_on_read_or_quote_preserves_directory(tmp_path, request_text):
    root = tmp_path/'workspace'; root.mkdir()
    (root/'notes.md').write_text('original notes')
    (root/'lesson.md').write_text('original lesson')
    (root/'保存.md').write_text('filename data')
    before = snapshot(root)
    requests=[]
    with client_at(tmp_path/'ws.db') as client, client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        grant=client.post('/api/v2/math-tutor/desktop/creator/workspaces',json={'path':str(root),'writable':True}).json()
        bind_gateway(get_product_state(), [tool_call(WRITE, {'workspace_id':grant['workspace_id'],'relative_path':'lesson.md',
            'content':'forbidden','expected_hash':hashlib.sha256(before['lesson.md']).hexdigest()}),answer('仅处理读取请求。')],requests)
        send(ws,'send_message','forced-read',{'text':request_text})
        assert WRITE not in [t['function']['name'] for t in requests[0]['tools']]
        receipt=next(json.loads(m['content']) for m in requests[-1]['messages'] if m['role']=='tool')
        assert receipt['ok'] is False
        assert snapshot(root)==before


def test_real_ws_cross_workspace_and_path_rejected_then_explicit_target_succeeds(tmp_path):
    roots=[tmp_path/'Primary',tmp_path/'Other']
    for root in roots: root.mkdir()
    requests=[]
    with client_at(tmp_path/'scoped.db') as client, client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        grants=[client.post('/api/v2/math-tutor/desktop/creator/workspaces',json={'path':str(root),'writable':True}).json() for root in roots]
        base=dict(relative_path='result.md',content='allowed')
        bind_gateway(get_product_state(),[
            tool_call(WRITE,{**base,'workspace_id':grants[1]['workspace_id']}),
            tool_call(WRITE,{**base,'workspace_id':grants[0]['workspace_id'],'relative_path':'unrequested.md'}),
            tool_call(WRITE,{**base,'workspace_id':grants[0]['workspace_id']}),answer('已保存明确请求的result.md。')],requests)
        send(ws,'send_message','scoped-save',{'text':'请在 Primary 目录保存 result.md'})
        receipts=[json.loads(m['content']) for m in requests[-1]['messages'] if m['role']=='tool']
        assert [r['ok'] for r in receipts]==[False,False,True]
        assert snapshot(roots[0])=={'result.md':b'allowed'} and snapshot(roots[1])=={}
