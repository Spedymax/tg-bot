"""Compare dungeon balance locally without a database or Telegram calls."""
import argparse
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from services import dungeon_logic as current


def choose_action(module, state, content, strategy, day, player, bought):
    p = state['player']
    heal = int(module.POTION_HEAL * 1.3) if state['modifier'] == 'no_negativity' else module.POTION_HEAL
    actions = {a['id'] for a in module.available_actions(state, content) if not a.get('disabled')}
    if state['phase'] == 'cleared':
        return 'potion' if 'potion' in actions and p['hp'] <= p['max_hp'] - heal else 'next'
    room = state['rooms'][state['room_index']]
    kind = room['type']
    if kind in ('fight', 'boss'):
        period = 3 if state['modifier'] == 'old_god' else 4
        if strategy == 'tactical' and kind == 'boss' and (state['room_state']['turn'] + 1) % period == 0:
            return 'defend'
        if 'potion' in actions and p['hp'] <= p['max_hp'] - heal:
            return 'potion'
        if strategy != 'block' and 'special' in actions:
            return 'special'
        return 'defend' if strategy == 'block' else 'attack'
    if kind in ('riddle', 'puzzle', 'npc'):
        correct = random.Random(f'answer:{day}:{player}:{room["index"]}').random() < 0.75
        options = (room.get('riddle') or room['npc'])['options']
        answer = room['hidden']['answer']
        return f'answer:{answer if correct else (answer + 1) % len(options)}'
    if kind == 'trap':
        # Choose by the authored option's intended outcome, never the hidden daily outcome.
        template = next(t for t in content['traps'] if t['title'] == room['trap']['title'])
        authored = template.get('outcomes', [])
        for outcome in ('heal', 'atk', 'potion', 'loot', 'jackpot', 'safe'):
            if outcome in authored:
                return f'trap:{authored.index(outcome)}'
        return 'trap:0'
    if kind == 'treasure':
        return 'chest:0'
    if kind == 'rest':
        return 'rest'
    if kind == 'merchant':
        for key, limit in [('potion', 2), ('shield', 1), ('whetstone', 1)]:
            if bought.get(key, 0) < limit and f'buy:{key}' in actions:
                bought[key] = bought.get(key, 0) + 1
                return f'buy:{key}'
        return 'leave'
    raise ValueError(kind)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=20)
    parser.add_argument('--players-per-day', type=int, default=10)
    parser.add_argument('--baseline-ref', default='HEAD')
    parser.add_argument('--rage', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.days < 1 or args.players_per_day < 1:
        parser.error('days and players-per-day must be positive')
    baseline = types.ModuleType('baseline_dungeon_logic')
    baseline_commit = subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', args.baseline_ref], text=True).strip()
    source = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                      f'{args.baseline_ref}:src/services/dungeon_logic.py'], text=True)
    exec(compile(source, 'baseline_dungeon_logic', 'exec'), baseline.__dict__)
    content = json.loads((ROOT / 'assets/data/dungeon_content.json').read_text())
    lore = {'players': ['A', 'B', 'C'], 'messages': [{'name': 'A', 'text': 'Synthetic quote'}],
            'highlights': [{'name': 'B', 'text': 'Synthetic highlight'}]}
    rows = []
    for version, module in [('baseline', baseline), ('package_1', current)]:
        for strategy in ('attack', 'block', 'tactical'):
            for modifier in current.MODIFIER_KEYS:
                wins = cleared = hp = 0
                for day in range(args.days):
                    layout = module.generate_layout(f'balance-day:{day}', content, lore, rage=args.rage)
                    for player in range(args.players_per_day):
                        state = module.new_run(f'balance-player:{day}:{player}', copy.deepcopy(layout), modifier)
                        bought = {}
                        for _ in range(300):
                            if module.is_finished(state):
                                break
                            action = choose_action(module, state, content, strategy, day, player, bought)
                            module.apply_action(state, action, content)
                        if not module.is_finished(state):
                            raise RuntimeError(f'Unfinished run: {version}/{strategy}/{modifier}/{day}/{player}')
                        win = state['phase'] == 'won'
                        wins += win
                        cleared += state['rooms_cleared']
                        hp += state['player']['hp'] if win else 0
                runs = args.days * args.players_per_day
                rows.append({'version': version, 'strategy': strategy, 'modifier': modifier,
                             'runs': runs, 'wins': wins, 'win_pct': round(wins * 100 / runs, 1),
                             'mean_rooms': round(cleared / runs, 2),
                             'winner_hp': round(hp / wins, 1) if wins else None})
            selected = [r for r in rows if r['version'] == version and r['strategy'] == strategy]
            print(json.dumps({'version': version, 'strategy': strategy,
                              'runs': sum(r['runs'] for r in selected),
                              'win_pct': round(sum(r['wins'] for r in selected) * 100 / sum(r['runs'] for r in selected), 1)},
                             ensure_ascii=False), flush=True)
    result = {'days': args.days, 'players_per_day': args.players_per_day,
              'baseline_ref': args.baseline_ref, 'baseline_commit': baseline_commit, 'answer_accuracy': 0.75,
              'rage': args.rage, 'trap_policy': 'authored intended outcomes, not hidden map outcomes',
              'notes': 'Synthetic simulations; all nine modifiers equally weighted, not real-player win rates.',
              'results': rows}
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
