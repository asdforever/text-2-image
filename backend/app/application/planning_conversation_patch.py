"""Deterministic conversation edits and three-way merging of current drafts."""
from copy import deepcopy
from uuid import UUID, uuid4

from ..core.errors import AppError


EDITABLE_FIELDS = {
    'taskTitle', 'moduleId', 'reason', 'suggestedCopy', 'compositionBrief',
    'informationQuestion', 'productPresence', 'subjectScale', 'layoutFamily',
    'evidence', 'previousModuleContrast', 'avoid', 'designGuideIds',
    'styleTemplateId', 'visualStyleTags', 'sceneTags', 'referenceCaseIds',
    'bigIdea', 'visualMechanism', 'regularOptions',
}
PLAN_FIELDS = {'summary', 'sharedVisualDirection', 'visualRhythm',
               'productPresencePlan', 'layoutFamilies', 'warnings'}
_ABSENT = object()


def _invalid(message):
    raise AppError('PLANNING_PATCH_INVALID', message, 400)


def _conflict(path):
    raise AppError('PLANNING_EDIT_CONFLICT', f'手动编辑与规划修改冲突：{path}，请基于当前方案重新调整', 409)


def _task(module):
    return module.get('taskId') or module['moduleId']


def _modules(snapshot):
    modules = snapshot['plan']['modules']
    ids = [_task(m) for m in modules]
    if len(ids) != len(set(ids)):
        _invalid('任务标识重复')
    return dict(zip(ids, modules))


def _parameters(values):
    if not isinstance(values, list) or len(values) > 20:
        _invalid('参数最多 20 项')
    for row in values:
        if (not isinstance(row, dict) or set(row) != {'key', 'value'}
                or not isinstance(row['key'], str) or not isinstance(row['value'], str)
                or len(row['key']) > 60 or len(row['value']) > 500):
            _invalid('参数名称或内容无效')


def apply_operations(snapshot: dict, operations: list[dict]) -> dict:
    result = deepcopy(snapshot)
    result.setdefault('parameterOverrides', {})
    result.setdefault('regularOptions', {})
    result.setdefault('taskDesignOverrides', {})
    if not isinstance(operations, list) or len(operations) > 100:
        _invalid('修改操作无效')
    for op in operations:
        if not isinstance(op, dict):
            _invalid('修改操作必须是对象')
        modules = _modules(result)
        kind = op.get('kind')
        if kind == 'set_plan':
            changes = op.get('changes', {})
            if not isinstance(changes, dict) or not changes or not set(changes) <= PLAN_FIELDS:
                _invalid('整体规划字段不可修改')
            result['plan'].update(deepcopy(changes))
        elif kind == 'add_module':
            module = deepcopy(op.get('module', {}))
            if (not isinstance(module, dict) or not isinstance(module.get('moduleId'), str)
                    or not module['moduleId'].strip()
                    or not set(module) <= (EDITABLE_FIELDS - {'regularOptions'}) | {'moduleParameters', 'resultCount', 'referenceModuleId'}):
                _invalid('新增任务无效')
            task = str(uuid4())
            if module.get('resultCount', 1) != 1 or isinstance(module.get('resultCount'), bool):
                _invalid('每个任务只能生成一张')
            module.update(taskId=task, resultCount=1)
            result['plan']['modules'].append(module)
        elif kind == 'reorder':
            order = op.get('taskIds')
            if (not isinstance(order, list) or not all(isinstance(key, str) for key in order)
                    or len(order) != len(modules) or set(order) != set(modules)):
                _invalid('排序必须包含每个任务一次')
            result['plan']['modules'] = [modules[task] for task in order]
        else:
            task = op.get('taskId')
            if not isinstance(task, str) or task not in modules:
                _invalid('要修改的任务不存在')
            if kind == 'set_module':
                changes = op.get('changes')
                if not isinstance(changes, dict) or not changes or not set(changes) <= EDITABLE_FIELDS:
                    _invalid('包含不可修改的规划字段')
                changes = deepcopy(changes)
                if changes.get('productPresence') == 'auto':
                    result['taskDesignOverrides'][task] = {'productPresence': changes.pop('productPresence')}
                elif 'productPresence' in changes:
                    result['taskDesignOverrides'].pop(task, None)
                if 'regularOptions' in changes:
                    result['regularOptions'][task] = changes.pop('regularOptions')
                modules[task].update(changes)
            elif kind == 'set_parameters':
                values = op.get('parameters')
                _parameters(values)
                result['parameterOverrides'][task] = deepcopy(values)
            elif kind == 'delete_module':
                result['plan']['modules'] = [m for m in result['plan']['modules'] if _task(m) != task]
                result['parameterOverrides'].pop(task, None)
                result['regularOptions'].pop(task, None)
                result['taskDesignOverrides'].pop(task, None)
            else:
                _invalid('未知修改操作')
    if not result['plan']['modules']:
        _invalid('至少保留一个任务')
    return result


def _merge_value(base, current, candidate, path):
    if current == candidate or candidate == base:
        return deepcopy(current) if current is not _ABSENT else _ABSENT
    if current == base:
        return deepcopy(candidate) if candidate is not _ABSENT else _ABSENT
    if all(isinstance(v, dict) for v in (base, current, candidate)):
        result = {}
        for key in dict.fromkeys([*base, *current, *candidate]):
            value = _merge_value(base.get(key, _ABSENT), current.get(key, _ABSENT),
                                 candidate.get(key, _ABSENT), f'{path}.{key}')
            if value is not _ABSENT:
                result[key] = value
        return result
    _conflict(path)


def _merge_order(base, current, candidate, ids, path):
    # Compare order of surviving shared tasks before including additions.
    shared = set(base) & set(current) & set(candidate) & ids
    b, c, a = [[key for key in order if key in shared] for order in (base, current, candidate)]
    if c != b and a != b and c != a:
        _conflict(path)
    preferred = current if a == b else candidate
    other = candidate if preferred is current else current
    order = [key for key in preferred if key in ids]
    for index, key in enumerate(other):
        if key not in ids or key in order:
            continue
        prior = next((p for p in reversed(other[:index]) if p in order), None)
        position = order.index(prior) + 1 if prior else 0
        order.insert(position, key)
    return order


def _merge_parameters(base, current, candidate, path):
    if candidate == base or current == candidate:
        return deepcopy(current)
    if current == base:
        return deepcopy(candidate)
    maps = []
    for rows in (base, current, candidate):
        keys = [row['key'] for row in rows]
        if len(keys) != len(set(keys)):
            _conflict(path)
        maps.append(dict(zip(keys, rows)))
    b, c, a = maps
    # Match a rename only when the unchanged value identifies one row uniquely.
    for index in (1, 2):
        side = maps[index]
        removed, added = set(b) - set(side), set(side) - set(b)
        matches = {}
        for old in removed:
            choices = [new for new in added if side[new]['value'] == b[old]['value']]
            if len(choices) == 1 and sum(b[key]['value'] == b[old]['value'] for key in removed) == 1:
                matches[choices[0]] = old
        if (removed - set(matches.values())) and (added - set(matches)):
            _conflict(path)
        maps[index] = {matches.get(key, key): row for key, row in side.items()}
    b, c, a = maps
    merged = _merge_value(b, c, a, path)
    order = _merge_order(list(b), list(c), list(a), set(merged), path)
    final_keys = [merged[key]['key'] for key in order]
    if len(final_keys) != len(set(final_keys)):
        _conflict(path)
    return [merged[key] for key in order]


def merge_candidate(base: dict, current: dict, candidate: dict) -> dict:
    b, c, a = [_modules(value) for value in (base, current, candidate)]
    # Editing parameters/options of a deleted task is also a conflict.
    for task in set(b) - (set(c) & set(a)):
        survivor = current if task in c else candidate
        if task in _modules(survivor):
            for channel in ('parameterOverrides', 'regularOptions', 'taskDesignOverrides'):
                if survivor.get(channel, {}).get(task) != base.get(channel, {}).get(task):
                    _conflict(f'{task}.{channel}')
    merged = _merge_value(b, c, a, 'modules')
    result = deepcopy(current)
    for key in dict.fromkeys([*base['plan'], *current['plan'], *candidate['plan']]):
        if key == 'modules':
            continue
        value = _merge_value(base['plan'].get(key, _ABSENT), current['plan'].get(key, _ABSENT),
                             candidate['plan'].get(key, _ABSENT), f'plan.{key}')
        if value is not _ABSENT:
            result['plan'][key] = value
        else:
            result['plan'].pop(key, None)
    order = _merge_order(list(b), list(c), list(a), set(merged), 'modules.order')
    result['plan']['modules'] = [merged[task] for task in order]
    result['parameterOverrides'] = {}
    for task in order:
        values = [value.get('parameterOverrides', {}).get(task, _ABSENT) for value in (base, current, candidate)]
        rows = (_merge_parameters(*values, f'{task}.parameters') if all(v is not _ABSENT for v in values)
                else _merge_value(*values, f'{task}.parameters'))
        if rows is not _ABSENT:
            result['parameterOverrides'][task] = rows
    result['regularOptions'] = _merge_value(base.get('regularOptions', {}), current.get('regularOptions', {}),
                                           candidate.get('regularOptions', {}), 'regularOptions')
    result['regularOptions'] = {k: v for k, v in result['regularOptions'].items() if k in merged}
    result['taskDesignOverrides'] = _merge_value(base.get('taskDesignOverrides', {}), current.get('taskDesignOverrides', {}),
                                                candidate.get('taskDesignOverrides', {}), 'taskDesignOverrides')
    result['taskDesignOverrides'] = {k: v for k, v in result['taskDesignOverrides'].items() if k in merged}
    return result


def _parameter_diff(left, right):
    left, right = left or [], right or []
    keys = [row['key'] for row in left + right]
    if any(len([row for row in rows if row['key'] == key]) > 1
           for rows in (left, right) for key in keys):
        return [{'kind': 'replaced', 'before': left, 'after': right}]
    before = {row['key']: row['value'] for row in left}
    after = {row['key']: row['value'] for row in right}
    removed = [key for key in before if key not in after]
    added = [key for key in after if key not in before]
    renames = {}
    for key in removed:
        matches = [new for new in added if after[new] == before[key]]
        if len(matches) == 1 and sum(before[old] == before[key] for old in removed) == 1:
            renames[key] = matches[0]
    renamed_keys = set(renames) | set(renames.values())
    changes = [{'key': key, 'newKey': new, 'kind': 'renamed', 'before': before[key], 'after': after[new]}
               for key, new in renames.items()]
    changes += [{'key': key, 'kind': 'added' if key not in before else 'deleted' if key not in after else 'changed',
             'before': before.get(key), 'after': after.get(key)}
            for key in dict.fromkeys(keys) if key not in renamed_keys and before.get(key, _ABSENT) != after.get(key, _ABSENT)]
    original, updated = list(before), list(after)
    changes += [{'key': key, 'kind': 'moved', 'before': original.index(key) + 1, 'after': updated.index(key) + 1}
                for key in original if key in after and original.index(key) != updated.index(key)]
    return changes


def diff_snapshots(base: dict, candidate: dict) -> list[dict]:
    before, after = _modules(base), _modules(candidate)
    changes = []
    for task in dict.fromkeys([*before, *after]):
        if task not in before or task not in after:
            changes.append({'kind': 'added' if task in after else 'deleted', 'taskId': task,
                            'before': before.get(task), 'after': after.get(task)})
            continue
        for field in dict.fromkeys([*before[task], *after[task]]):
            if before[task].get(field) != after[task].get(field):
                changes.append({'kind': 'field', 'taskId': task, 'field': field,
                                'before': before[task].get(field), 'after': after[task].get(field)})
        for channel in ('parameterOverrides', 'regularOptions', 'taskDesignOverrides'):
            left, right = base.get(channel, {}).get(task), candidate.get(channel, {}).get(task)
            if left != right:
                changes.append({'kind': 'field', 'taskId': task, 'field': channel, 'before': left, 'after': right,
                                **({'parameterChanges': _parameter_diff(left, right)} if channel == 'parameterOverrides' else {})})
        left, right = list(before).index(task), list(after).index(task)
        if left != right:
            changes.append({'kind': 'moved', 'taskId': task, 'before': left + 1, 'after': right + 1})
    for field in PLAN_FIELDS:
        if base['plan'].get(field) != candidate['plan'].get(field):
            changes.append({'kind': 'field', 'field': field,
                            'before': base['plan'].get(field), 'after': candidate['plan'].get(field)})
    return deepcopy(changes)
