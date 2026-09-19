import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services import dungeon_logic as logic

CONTENT = json.loads((Path(__file__).resolve().parents[1] / 'assets/data/dungeon_content.json').read_text())


def fight_state(version=2, boss=False, modifier='none'):
    room = {'type': 'boss' if boss else 'fight', 'index': 0, 'balance_version': version,
            'enemy': {'name': 'Test', 'emoji': '🗿', 'hp': 100, 'max_hp': 100, 'atk': 6}}
    return logic.new_run('test-combat', [room], modifier)


def test_generated_layouts_have_early_recovery_and_no_three_fights_without_it():
    for i in range(500):
        lore = {'players': ['A', 'B'], 'messages': [{'name': 'A', 'text': 'Hello'}]}
        rooms = logic.generate_layout(f'day:{i}', CONTENT, lore, rage=bool(i % 2))
        assert rooms == logic.generate_layout(f'day:{i}', CONTENT, lore, rage=bool(i % 2))
        kinds = [r['type'] for r in rooms]
        assert len(rooms) == 10 and kinds[-1] == 'boss'
        assert kinds.count('fight') == 4
        assert 3 <= kinds.index('rest') <= 5
        assert 4 <= kinds.index('merchant') <= 7
        fights = 0
        for kind in kinds:
            if kind in ('rest', 'merchant'):
                fights = 0
            elif kind in ('fight', 'boss'):
                fights += 1
                assert fights <= 2
        assert logic.new_run('test', rooms)['balance_version'] == 2


def test_authored_traps_keep_option_outcome_pairs_across_days():
    observed = set()
    for i in range(800):
        for room in logic.generate_layout(f'trap-day:{i}', CONTENT):
            if room['type'] != 'trap':
                continue
            trap = next(t for t in CONTENT['traps'] if t['title'] == room['trap']['title'])
            assert room['trap']['options'] == trap['options']
            assert room['hidden']['outcomes'] == trap['outcomes']
            assert not room['trap']['random_choice']
            observed.add(trap['title'])
    assert observed == {t['title'] for t in CONTENT['traps']}


def test_unmapped_traps_are_explicitly_random():
    content = copy.deepcopy(CONTENT)
    trap = content['traps'][0]
    del trap['outcomes']
    content['traps'] = [trap]
    for i in range(100):
        rooms = logic.generate_layout(f'random:{i}', content)
        if any(room['type'] == 'trap' for room in rooms):
            break
    else:
        raise AssertionError('No trap generated')
    index = next(i for i,r in enumerate(rooms) if r['type'] == 'trap')
    state = logic.new_run('random', rooms)
    state['room_index'] = index
    logic._enter_room(state)
    assert 'исход случаен' in logic.public_view(state, content)['room']['warning']


@pytest.mark.parametrize('modifier,expected', [('none', 12), ('no_negativity', 15)])
def test_between_room_potion_has_no_enemy_turn_and_logs_actual_healing(modifier, expected):
    state = fight_state(modifier=modifier)
    state['phase'] = 'cleared'
    state['rooms_cleared'] = 1
    state['player']['hp'] = 10
    before_enemy = copy.deepcopy(state['room_state'])
    assert 'potion' in {a['id'] for a in logic.available_actions(state, CONTENT)}
    logic.apply_action(state, 'potion', CONTENT)
    assert state['player']['hp'] == 10 + expected
    assert state['player']['potions'] == 0
    assert state['phase'] == 'cleared' and state['rooms_cleared'] == 1
    assert state['room_state'] == before_enemy
    assert state['history'][-1]['healed'] == expected
    assert state['history'][-1]['damage_taken'] == 0
    snapshot = copy.deepcopy(state)
    logic.apply_action(state, 'potion', CONTENT)
    assert state == snapshot


def test_full_hp_and_finished_runs_cannot_waste_between_room_potion():
    state = fight_state()
    for phase in ('cleared', 'dead', 'won'):
        state['phase'] = phase
        assert 'potion' not in {a['id'] for a in logic.available_actions(state, CONTENT)}


def test_combat_potion_still_allows_enemy_attack_and_records_both():
    state = fight_state()
    state['player']['hp'] = 10
    assert 'враг ответит' in next(a['label'] for a in logic.available_actions(state, CONTENT) if a['id'] == 'potion')
    logic.apply_action(state, 'potion', CONTENT)
    record = state['history'][-1]
    assert state['room_state']['turn'] == 1
    assert record['healed'] == 12
    assert 5 <= record['damage_taken'] <= 7
    assert record['hp_after'] == 22 - record['damage_taken']


def test_block_uses_sixty_percent_defence_and_half_attack_counter():
    attack = fight_state()
    block = copy.deepcopy(attack)
    logic.apply_action(attack, 'defend', CONTENT)
    # Same seed and step -> same enemy damage roll with legacy defence.
    block['balance_version'] = 1
    logic.apply_action(block, 'defend', CONTENT)
    assert attack['room_state']['enemy_hp'] == 97
    assert block['room_state']['enemy_hp'] == 98
    assert attack['history'][-1]['damage_taken'] == 2
    assert block['history'][-1]['damage_taken'] == 3


@pytest.mark.parametrize('modifier,period', [('none', 4), ('old_god', 3)])
def test_bite_warning_precedes_actual_bite_and_block_protects(modifier, period):
    state = fight_state(boss=True, modifier=modifier)
    state['room_state']['turn'] = period - 1
    assert 'Следующий удар — двойной' in logic.public_view(state, CONTENT)['room']['warning']
    attack = copy.deepcopy(state)
    logic.apply_action(state, 'defend', CONTENT)
    logic.apply_action(attack, 'attack', CONTENT)
    assert state['history'][-1]['damage_taken'] < attack['history'][-1]['damage_taken']
    assert not logic.public_view(state, CONTENT)['room']['warning']


def test_legacy_layouts_keep_legacy_rules_even_for_new_runs():
    state = fight_state(version=1, boss=True)
    del state['rooms'][0]['balance_version']
    legacy = logic.new_run('legacy', state['rooms'])
    assert legacy['balance_version'] == 1
    legacy['phase'] = 'cleared'
    legacy['player']['hp'] = 10
    assert [a['id'] for a in logic.available_actions(legacy, CONTENT)] == ['next']
    legacy['phase'] = 'room'
    legacy['room_state']['turn'] = 3
    assert not logic.public_view(legacy, CONTENT)['room']['warning']
    assert 'удар 2' in next(a['label'] for a in logic.available_actions(legacy, CONTENT) if a['id'] == 'defend')


def test_history_survives_restart_and_does_not_truncate_with_chronicle():
    state = fight_state()
    state['rooms'][0]['enemy']['atk'] = 0
    state['rooms'][0]['enemy']['hp'] = state['rooms'][0]['enemy']['max_hp'] = 1000
    state['room_state']['enemy_hp'] = 1000
    for _ in range(45):
        logic.apply_action(state, 'defend', CONTENT)
    assert len(state['log']) == 40
    assert len(state['history']) == 45
    restored = json.loads(json.dumps(state))
    logic.apply_action(state, 'defend', CONTENT)
    logic.apply_action(restored, 'defend', CONTENT)
    assert restored == state
    snapshot = copy.deepcopy(state)
    logic.apply_action(state, 'invalid', CONTENT)
    assert state == snapshot


def test_entering_next_room_clears_visible_messages_but_keeps_chronicle():
    rooms = [
        {'type': 'fight', 'index': 0, 'balance_version': 2,
         'enemy': {'name': 'Первый', 'emoji': '👺', 'hp': 1, 'max_hp': 1, 'atk': 0}},
        {'type': 'fight', 'index': 1, 'balance_version': 2,
         'enemy': {'name': 'Второй', 'emoji': '🐀', 'hp': 10, 'max_hp': 10, 'atk': 0}},
    ]
    state = logic.new_run('rooms', rooms)
    logic.apply_action(state, 'attack', CONTENT)
    assert state['phase'] == 'cleared'
    logic.apply_action(state, 'next', CONTENT)
    view = logic.public_view(state, CONTENT)
    assert all('Первый' not in line for line in view['log'])
    assert any('Второй' in line for line in view['log'])
    assert any('Первый' in line for line in view['chronicle'])


def test_special_hint_does_not_consume_inventory_or_allow_second_use():
    state = fight_state()
    assert 'Предмет из инвентаря не тратится' in logic.public_view(state, CONTENT)['room']['hint']
    logic.apply_action(state, 'special', CONTENT)
    assert state['player']['special_used']
    assert not logic.public_view(state, CONTENT)['room']['hint']
    assert 'special' not in {a['id'] for a in logic.available_actions(state, CONTENT)}
