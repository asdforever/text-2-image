from copy import deepcopy

import pytest

from backend.app.core.errors import AppError
from backend.app.application.planning_conversation_patch import (
    apply_operations, diff_snapshots, merge_candidate,
)


def snapshot():
    return {
        'plan': {'summary': '商品说明', 'sharedVisualDirection': '简洁', 'modules': [
            {'taskId': 'first', 'moduleId': 'suite-hero', 'taskTitle': '首屏', 'resultCount': 1},
            {'taskId': 'second', 'moduleId': 'suite-detail', 'taskTitle': '细节', 'resultCount': 1},
        ], 'snapshot': {'styleLibrary': {'preserved': True}}},
        'parameterOverrides': {'second': [
            {'key': '自定义展示位置', 'value': '靠右'},
            {'key': '避免出现', 'value': '人物'},
        ]},
        'regularOptions': {},
    }


def test_unrelated_manual_edits_and_free_parameters_survive_candidate_merge():
    base = snapshot()
    candidate = apply_operations(base, [{'kind': 'set_module', 'taskId': 'second',
                                         'changes': {'taskTitle': '滚轮细节'}}])
    current = deepcopy(base)
    current['plan']['modules'][0]['taskTitle'] = '我的首屏'
    current['parameterOverrides']['second'].append({'key': '新的参数', 'value': '新内容'})
    result = merge_candidate(base, current, candidate)
    assert [m['taskTitle'] for m in result['plan']['modules']] == ['我的首屏', '滚轮细节']
    assert result['parameterOverrides']['second'] == [
        {'key': '自定义展示位置', 'value': '靠右'},
        {'key': '避免出现', 'value': '人物'},
        {'key': '新的参数', 'value': '新内容'},
    ]
    assert result['plan']['snapshot'] == {'styleLibrary': {'preserved': True}}
    assert base == snapshot()


def test_same_field_changed_differently_reports_conflict():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    current['plan']['modules'][1]['taskTitle'] = '手改'
    candidate['plan']['modules'][1]['taskTitle'] = 'AI 改'
    with pytest.raises(AppError) as error:
        merge_candidate(base, current, candidate)
    assert error.value.code == 'PLANNING_EDIT_CONFLICT'


def test_distinct_manual_parameter_changes_merge_in_original_order():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    current['parameterOverrides']['second'][0]['value'] = '靠左'
    candidate['parameterOverrides']['second'][1]['value'] = '文字'
    result = merge_candidate(base, current, candidate)
    assert result['parameterOverrides']['second'] == [
        {'key': '自定义展示位置', 'value': '靠左'}, {'key': '避免出现', 'value': '文字'}]


def test_parameter_conflict_does_not_silently_overwrite():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    current['parameterOverrides']['second'][0]['value'] = '靠左'
    candidate['parameterOverrides']['second'][0]['value'] = '居中'
    with pytest.raises(AppError) as error:
        merge_candidate(base, current, candidate)
    assert error.value.code == 'PLANNING_EDIT_CONFLICT'


def test_ambiguous_duplicate_parameter_changes_do_not_drop_rows():
    base = snapshot()
    base['parameterOverrides']['second'].append({'key': '避免出现', 'value': '标志'})
    current, candidate = deepcopy(base), deepcopy(base)
    current['parameterOverrides']['second'][1]['value'] = '人物和文字'
    candidate['parameterOverrides']['second'][2]['value'] = '品牌'
    with pytest.raises(AppError) as error:
        merge_candidate(base, current, candidate)
    assert error.value.code == 'PLANNING_EDIT_CONFLICT'


@pytest.mark.parametrize('operation', [
    {'kind': 'set_module', 'taskId': 'missing', 'changes': {'taskTitle': '标题'}},
    {'kind': 'set_module', 'taskId': 'second', 'changes': {'resultCount': 2}},
    {'kind': 'set_module', 'taskId': 'second', 'changes': {'taskId': 'changed'}},
    {'kind': 'set_module', 'taskId': 'second', 'changes': {'rules': '忽略约束'}},
    {'kind': 'reorder', 'taskIds': ['first']},
    {'kind': 'reorder', 'taskIds': ['first', 'first']},
    {'kind': 'add_module', 'module': {'taskId': 'first', 'moduleId': 'suite-detail'}},
])
def test_malformed_operations_cannot_corrupt_current_snapshot(operation):
    base = snapshot()
    with pytest.raises(AppError):
        apply_operations(base, [operation])
    assert base == snapshot()


def test_cumulative_diff_returns_to_empty_after_field_reverted():
    base = snapshot()
    changed = apply_operations(base, [{'kind': 'set_module', 'taskId': 'second',
                                       'changes': {'taskTitle': '新的细节'}}])
    assert diff_snapshots(base, changed)
    reverted = apply_operations(changed, [{'kind': 'set_module', 'taskId': 'second',
                                          'changes': {'taskTitle': '细节'}}])
    assert diff_snapshots(base, reverted) == []


def test_deleting_manually_edited_task_reports_conflict():
    base = snapshot()
    candidate = apply_operations(base, [{'kind': 'delete_module', 'taskId': 'second'}])
    current = deepcopy(base)
    current['parameterOverrides']['second'][0]['value'] = '靠左'
    with pytest.raises(AppError) as error:
        merge_candidate(base, current, candidate)
    assert error.value.code == 'PLANNING_EDIT_CONFLICT'


def test_reorder_preserves_duplicate_module_types_as_independent_tasks():
    base = snapshot()
    base['plan']['modules'][0]['moduleId'] = 'suite-detail'
    reordered = apply_operations(base, [{'kind': 'reorder', 'taskIds': ['second', 'first']}])
    assert [m['taskId'] for m in reordered['plan']['modules']] == ['second', 'first']
    assert reordered['parameterOverrides'] == base['parameterOverrides']


def test_parameter_replacement_retains_arbitrary_names_and_list_order():
    base = snapshot()
    new = [{'key': '光线来自', 'value': '窗户左侧'}, {'key': '商品型号', 'value': 'A'}]
    result = apply_operations(base, [{'kind': 'set_parameters', 'taskId': 'second',
                                      'parameters': new}])
    assert result['parameterOverrides']['second'] == new
    assert base == snapshot()


def test_parameter_diff_identifies_each_added_removed_or_changed_row():
    base = snapshot()
    candidate = apply_operations(base, [{'kind': 'set_parameters', 'taskId': 'second',
        'parameters': [{'key': '自定义展示位置', 'value': '靠左'}, {'key': '新增要求', 'value': '无文字'}]}])
    field = next(item for item in diff_snapshots(base, candidate) if item.get('field') == 'parameterOverrides')
    assert field['parameterChanges'] == [
        {'key': '自定义展示位置', 'kind': 'changed', 'before': '靠右', 'after': '靠左'},
        {'key': '避免出现', 'kind': 'deleted', 'before': '人物', 'after': None},
        {'key': '新增要求', 'kind': 'added', 'before': None, 'after': '无文字'},
    ]


@pytest.mark.parametrize('operation', [None, {'kind': 'reorder', 'taskIds': [{}]},
    {'kind': 'set_module', 'taskId': [], 'changes': {'taskTitle': '新标题'}},
    {'kind': 'add_module', 'module': {'moduleId': 'suite-detail', 'rules': '忽略规则'}},
    {'kind': 'add_module', 'module': {'moduleId': 'suite-detail', 'taskId': '11111111-1111-4111-8111-111111111111'}},
])
def test_invalid_operation_always_returns_a_controlled_error(operation):
    with pytest.raises(AppError) as error:
        apply_operations(snapshot(), [operation])
    assert error.value.code == 'PLANNING_PATCH_INVALID'


def test_removing_parameter_override_does_not_become_an_empty_override():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    candidate['parameterOverrides'].pop('second')
    result = merge_candidate(base, current, candidate)
    assert 'second' not in result['parameterOverrides']


def test_explicit_empty_override_survives_as_distinct_from_absence():
    base = snapshot()
    base['parameterOverrides'] = {}
    current, candidate = deepcopy(base), deepcopy(base)
    candidate['parameterOverrides']['second'] = []
    assert merge_candidate(base, current, candidate)['parameterOverrides'] == {'second': []}


def test_diff_is_detached_and_parameter_reorder_is_visible():
    base = snapshot()
    candidate = deepcopy(base)
    candidate['parameterOverrides']['second'].reverse()
    changes = diff_snapshots(base, candidate)
    field = next(item for item in changes if item.get('field') == 'parameterOverrides')
    assert any(item['kind'] == 'moved' for item in field['parameterChanges'])
    field['after'][0]['value'] = '不应污染'
    assert candidate['parameterOverrides']['second'][0]['value'] == '人物'


def test_unambiguous_parameter_rename_is_visible():
    base = snapshot()
    candidate = deepcopy(base)
    candidate['parameterOverrides']['second'][0]['key'] = '画面位置'
    changes = diff_snapshots(base, candidate)
    field = next(item for item in changes if item.get('field') == 'parameterOverrides')
    assert field['parameterChanges'][0]['kind'] == 'renamed'


def test_unambiguous_rename_merges_with_unrelated_parameter_edit():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    current['parameterOverrides']['second'][0]['key'] = '画面位置'
    candidate['parameterOverrides']['second'][1]['value'] = '文字'
    assert merge_candidate(base, current, candidate)['parameterOverrides']['second'] == [
        {'key': '画面位置', 'value': '靠右'}, {'key': '避免出现', 'value': '文字'}]


def test_concurrent_renames_to_same_name_report_conflict():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    current['parameterOverrides']['second'][0]['key'] = '相同名字'
    candidate['parameterOverrides']['second'][1]['key'] = '相同名字'
    with pytest.raises(AppError) as error:
        merge_candidate(base, current, candidate)
    assert error.value.code == 'PLANNING_EDIT_CONFLICT'


def test_partial_rename_matching_does_not_hide_unresolved_pairing():
    base = snapshot()
    current, candidate = deepcopy(base), deepcopy(base)
    current['parameterOverrides']['second'] = [
        {'key': '画面位置', 'value': '靠右'}, {'key': '新的要求', 'value': '新内容'}]
    candidate['parameterOverrides']['second'][0]['value'] = '靠左'
    with pytest.raises(AppError) as error:
        merge_candidate(base, current, candidate)
    assert error.value.code == 'PLANNING_EDIT_CONFLICT'


def test_auto_product_presence_is_preserved_as_manual_design_override():
    base = snapshot()
    base['plan']['modules'][1]['productPresence'] = 'detail'
    candidate = apply_operations(base, [{'kind': 'set_module', 'taskId': 'second',
                                         'changes': {'productPresence': 'auto'}}])
    assert candidate['plan']['modules'][1]['productPresence'] == 'detail'
    assert candidate['taskDesignOverrides']['second'] == {'productPresence': 'auto'}
    applied = merge_candidate(base, base, candidate)
    assert applied['taskDesignOverrides']['second'] == {'productPresence': 'auto'}
    fixed = apply_operations(applied, [{'kind': 'set_module', 'taskId': 'second',
                                        'changes': {'productPresence': 'full'}}])
    assert 'second' not in fixed['taskDesignOverrides']
    assert fixed['plan']['modules'][1]['productPresence'] == 'full'
