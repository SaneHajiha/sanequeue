"""Known legacy migration only; no stock dialplan or privileged apply is inferred."""
import ast
import os
from pathlib import Path
import re

import pytest


if os.name == 'nt':
    # The production helper imports Linux-only pwd/grp. Execute its unchanged,
    # pure string-transform unit on Windows without stubbing privileged APIs.
    path = Path(__file__).resolve().parents[1] / 'sanequeue/pbx/root_adapter.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name == 'patch_macro' or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MARKER' for t in node.targets)]
    namespace = {'re': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    patch_macro, MARKER = namespace['patch_macro'], namespace['MARKER']
else:
    from sanequeue.pbx.root_adapter import patch_macro, MARKER


PREFIX = '; unrelated configuration\n[before]\nexten => s,n(dial),Dial(SIP/901)\n'
HEADER = '[macro-dial-one]\n'
BODY = ('exten => s,1,Set(DEXTEN=${ARG2})\n'
        '###CallWaiting And CallBack\n'
        'exten => s,n(godial),NoOp(legacy owner menu)\n'
        'exten => s,n,NoOp(legacy implementation)\n'
        'exten => s,n(dial),Dial(${DSTRING},${ARG1},${D_OPTIONS})\n'
        'exten => s,n,Return()\n')
SUFFIX = '[after]\nexten => s,n(dial),Dial(PJSIP/902)\n; keep exactly\n'


def original(body=BODY):
    return PREFIX + HEADER + body + SUFFIX


def test_legacy_block_is_replaced_inside_exact_context_only():
    value = patch_macro(original())
    assert value.startswith(PREFIX + HEADER)
    assert value.endswith(SUFFIX)
    assert 'legacy owner menu' not in value
    assert value.count(MARKER) == 1
    assert ('exten => s,n(godial),Gosub(sanequeue-busy-menu,s,1(${DEXTEN}))\n\n'
            'exten => s,n(dial),Gosub(sanequeue-caller-name,s,1(${NODEST},${SANEQUEUE_CALLBACK}))\n'
            'exten => s,n,Dial(${DSTRING},${ARG1},${D_OPTIONS})\n') in value
    assert 'exten => s,n,Return()\n' in value


def test_managed_signature_is_idempotent_and_old_name_hook_is_upgraded():
    value = patch_macro(original())
    assert patch_macro(value) == value
    old = value.replace('${NODEST},${SANEQUEUE_CALLBACK}', '${NODEST}')
    assert patch_macro(old) == value
    assert patch_macro(patch_macro(old)) == value


def test_crlf_and_unrelated_managed_comment_are_preserved():
    source = original().replace('\n', '\r\n')
    value = patch_macro(source)
    assert '\n' not in value.replace('\r\n', '')
    assert patch_macro(value) == value
    unrelated = MARKER + '\n' + original()
    assert patch_macro(unrelated).startswith(MARKER + '\n' + PREFIX)


INBOUND_GUARD = 'exten => s,n,ExecIf($["${DIRECTION}" = "INBOUND"]?Set(D_OPTIONS=${STRREPLACE(D_OPTIONS,T)}))\n'


def managed_with_inbound_guard():
    return patch_macro(original()).replace(
        'exten => s,n,Dial(${DSTRING},${ARG1},${D_OPTIONS})\n',
        INBOUND_GUARD + 'exten => s,n,Dial(${DSTRING},${ARG1},${D_OPTIONS}b(func-apply-sipheaders^s^1))\n')


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_observed_exact_inbound_guard_is_preserved_and_idempotent(newline):
    source = managed_with_inbound_guard().replace('\n', newline)
    assert patch_macro(source) == source
    assert patch_macro(patch_macro(source)) == source
    old = source.replace('${NODEST},${SANEQUEUE_CALLBACK}', '${NODEST}')
    assert patch_macro(old) == source
    assert PREFIX.replace('\n', newline) in source
    assert source.endswith(SUFFIX.replace('\n', newline))


@pytest.mark.parametrize('replacement', [
    INBOUND_GUARD + INBOUND_GUARD,
    INBOUND_GUARD.replace('INBOUND', 'OUTBOUND'),
    INBOUND_GUARD.replace('STRREPLACE(D_OPTIONS,T)', 'STRREPLACE(D_OPTIONS,t)'),
    'exten => s,n,NoOp(unrecognized intermediary)\n' + INBOUND_GUARD,
    INBOUND_GUARD + 'exten => s,n,System(unrecognized command)\n',
])
def test_optional_inbound_guard_must_match_the_observed_exact_signature(replacement):
    with pytest.raises(ValueError, match='unsupported_dial_one_adapter'):
        patch_macro(managed_with_inbound_guard().replace(INBOUND_GUARD, replacement))


@pytest.mark.parametrize('source', [
    '', None, PREFIX + SUFFIX,
    original().replace('[macro-dial-one]', '[other-macro]'),
    original() + '[macro-dial-one]\nexten => s,1,Return()\n',
    original().replace('[macro-dial-one]', '[macro-dial-one](+)'),
    original(BODY.replace('###CallWaiting And CallBack\n', '')),
    original(BODY.replace('###CallWaiting And CallBack', MARKER)),
    original(BODY.replace('###CallWaiting And CallBack', '###CallWaiting And CallBack extra')),
    original(BODY.replace('###CallWaiting And CallBack\n', '###CallWaiting And CallBack\n###CallWaiting And CallBack\n')),
    original(BODY.replace('exten => s,n(dial),', 'exten => s,n(other),')),
    original(BODY + 'same => n(dial),Dial(PJSIP/999)\n'),
    original(BODY + 'exten  => s,n(dial),Dial(PJSIP/999)\n'),
    original(BODY.replace('Dial(${DSTRING},${ARG1},${D_OPTIONS})', 'NoOp(unknown application)')),
    original(BODY.replace('###CallWaiting And CallBack\n', 'exten => s,n(godial),NoOp(unrelated branch)\n###CallWaiting And CallBack\n')),
    # A later context's dial label must never satisfy a missing local label.
    original(BODY.replace('exten => s,n(dial),Dial(${DSTRING},${ARG1},${D_OPTIONS})\n', '')),
    original(BODY + 'exten => s,n,NoOp(sanequeue-busy-menu)\n'),
])
def test_missing_malformed_or_ambiguous_legacy_signature_is_rejected(source):
    with pytest.raises(ValueError, match='unsupported_dial_one_adapter'):
        patch_macro(source)


@pytest.mark.parametrize('change', [
    lambda s: s.replace(MARKER, MARKER + '\n' + MARKER),
    lambda s: s.replace(MARKER, MARKER + '\n###CallWaiting And CallBack'),
    lambda s: s.replace('sanequeue-busy-menu,s,1(${DEXTEN})', 'sanequeue-busy-menu,s,1(999)'),
    lambda s: s.replace('sanequeue-caller-name,s,1(${NODEST},${SANEQUEUE_CALLBACK})', 'sanequeue-caller-name,s,1(999)'),
    lambda s: s.replace('exten => s,n,Dial(', 'exten => s,n,Unknown('),
    lambda s: s.replace('exten => s,n,Return()', 'exten => s,n,NoOp(sanequeue-caller-name)'),
    lambda s: s.replace('exten => s,n(dial),Gosub', 'exten => s,n(other),Gosub'),
    lambda s: s.replace(MARKER, '; modified ' + MARKER),
    lambda s: s.replace('exten => s,n,Return()', 'same => n(godial),Return()'),
])
def test_partial_or_modified_managed_signature_is_rejected(change):
    with pytest.raises(ValueError, match='unsupported_dial_one_adapter'):
        patch_macro(change(patch_macro(original())))
