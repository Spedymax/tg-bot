"""
Daily dungeon — pure game logic, no I/O.

One layout per calendar day is generated from a seed and shared by every player
(fair race: «Юра дошёл до 8, а ты сдох в 4»). Every action is resolved server-side
with an RNG seeded by (run seed, step number), so reloading the page or replaying
a request can never re-roll an outcome.

State shape (stored as JSONB per player per day):
{
  "balance_version": int, "history": [action_record, ...],
  "seed": str, "step": int, "room_index": int,           # 0-based, 9 = mini-Pudge
  "rooms": [room, ...],                                    # from generate_layout (hidden keys included)
  "player": {"hp","max_hp","atk","gold","potions","shield","special_used"},
  "phase": "room" | "cleared" | "dead" | "won",
  "room_state": {...},                                     # per-room scratch (enemy hp, turn, purchases)
  "log": [str, ...],                                       # narrated events, newest last
  "rooms_cleared": int, "boss_killed": bool
}
"""
import math
import random
from typing import Optional

ROOMS = 10
BOSS_ROOM = ROOMS - 1

BASE_PLAYER = {'hp': 32, 'max_hp': 32, 'atk': 5, 'gold': 0, 'potions': 1, 'shield': 0, 'special_used': False}
POTION_HEAL = 12
REST_HEAL = 14
CRIT_CHANCE = 0.15
BALANCE_VERSION = 2


def _rng(seed: str, step) -> random.Random:
    return random.Random(f"{seed}:{step}")


MODIFIER_KEYS = ['none', 'no_negativity', 'lowkey', 'prime', 'sheva', 'reveal', 'dai_bozhe', 'torsion', 'old_god']


def daily_modifier(day_seed: str) -> str:
    """One «правило дня» for everyone; 'none' roughly one day in four."""
    r = _rng(day_seed, 'modifier')
    return 'none' if r.random() < 0.25 else r.choice(MODIFIER_KEYS[1:])


def _new_balance(state: dict) -> bool:
    return state.get('balance_version', 1) >= 2


def _mod(state: dict) -> str:
    return state.get('modifier') or 'none'


# ── layout generation ─────────────────────────────────────────────────────────
def _scale_enemy(base: dict, idx: int, rage: bool) -> dict:
    e = dict(base)
    e['hp'] = base['hp'] + idx * 2
    e['max_hp'] = e['hp']
    e['atk'] = base['atk'] + idx // 3 + (1 if rage else 0)
    return e


def _procedural_puzzle(r: random.Random) -> dict:
    kind = r.choice(['arith', 'geom', 'squares', 'mult'])
    if kind == 'arith':
        a, d = r.randint(2, 15), r.randint(3, 9)
        seq = [a + d * i for i in range(5)]
        answer = a + d * 5
        q = f"Продолжи ряд: {', '.join(map(str, seq))}, ?"
    elif kind == 'geom':
        a, k = r.randint(1, 4), r.choice([2, 3])
        seq = [a * k ** i for i in range(4)]
        answer = a * k ** 4
        q = f"Продолжи ряд: {', '.join(map(str, seq))}, ?"
    elif kind == 'squares':
        s = r.randint(2, 6)
        seq = [i * i for i in range(s, s + 4)]
        answer = (s + 4) ** 2
        q = f"Продолжи ряд: {', '.join(map(str, seq))}, ?"
    else:
        x, y = r.randint(12, 29), r.randint(3, 9)
        answer = x * y
        q = f"Сколько будет {x} × {y}?"
    wrong = set()
    while len(wrong) < 3:
        delta = r.choice([-1, 1]) * r.randint(1, max(3, abs(answer) // 6 + 2))
        if answer + delta != answer and answer + delta > 0:
            wrong.add(answer + delta)
    options = [str(answer)] + [str(w) for w in sorted(wrong)]
    r.shuffle(options)
    return {'q': q, 'options': options, 'a': options.index(str(answer))}


def generate_layout(seed: str, content: dict, lore: Optional[dict] = None, rage: bool = False) -> list:
    """lore = {'players': [name,...], 'highlights': [{'name','text'}], 'messages': [{'name','text'}]}"""
    lore = lore or {}
    r = _rng(seed, 'layout')
    players = list(lore.get('players') or [])
    messages = [m for m in (lore.get('messages') or []) if m.get('name') in players] if len(players) >= 2 else []
    highlights = list(lore.get('highlights') or [])

    kinds = ['fight', 'fight', 'fight', 'fight', 'riddle', 'puzzle', 'rest', 'merchant']
    extras = ['treasure', 'trap'] + (['npc'] if messages else [])
    r.shuffle(extras)
    kinds += extras[:1]
    def recoverable(order):
        if not 3 <= order.index('rest') <= 5 or not 4 <= order.index('merchant') <= 7:
            return False
        fights = 0
        for kind in order + ['boss']:
            if kind in ('rest', 'merchant'):
                fights = 0
            elif kind in ('fight', 'boss'):
                fights += 1
                if fights > 2:
                    return False
        return True

    for _ in range(2000):
        r.shuffle(kinds)
        if recoverable(kinds):
            break
    else:
        # Guaranteed valid fallback, still using the day's selected extra rooms.
        kinds = ['riddle', 'fight', 'fight', 'rest', 'puzzle', 'merchant',
                 'fight', 'fight', *extras[:1]]

    enemies = list(content.get('enemies') or [])
    r.shuffle(enemies)
    riddles = list(content.get('riddles') or [])
    r.shuffle(riddles)
    traps = list(content.get('traps') or [])
    r.shuffle(traps)
    flavor = list(content.get('room_flavor') or [''])
    rooms = []
    fight_no = 0
    for idx, kind in enumerate(kinds):
        room = {'type': kind, 'index': idx, 'flavor': r.choice(flavor)}
        if kind == 'fight':
            fight_no += 1
            # the second fight is the «высер недели» if we have one
            if fight_no == 2 and highlights:
                h = r.choice(highlights)
                tpl = content.get('highlight_enemy', {})
                text = (h.get('text') or '').strip()[:140]
                base = {
                    'name': f"{tpl.get('name', 'Высер недели')}: {h.get('name', '?')}",
                    'emoji': tpl.get('emoji', '💩'), 'hp': 15, 'atk': 4,
                    'intro': tpl.get('intro', '').format(text=text, name=h.get('name', '?')),
                    'taunts': [text] if text else [],
                    'image': tpl.get('image'),
                }
            else:
                base = enemies[(fight_no - 1) % len(enemies)] if enemies else {'name': 'Гоблин', 'emoji': '👺', 'hp': 12, 'atk': 4, 'intro': '', 'taunts': []}
            room['enemy'] = _scale_enemy(base, idx, rage)
        elif kind == 'riddle':
            rd = riddles[idx % len(riddles)] if riddles else {'q': '2+2?', 'options': ['3', '4', '5', '22'], 'a': 1}
            room['riddle'] = {'q': rd['q'], 'options': list(rd['options'])}
            room['hidden'] = {'answer': rd['a']}
        elif kind == 'puzzle':
            pz = _procedural_puzzle(r)
            room['riddle'] = {'q': pz['q'], 'options': pz['options']}
            room['hidden'] = {'answer': pz['a']}
        elif kind == 'treasure':
            contents = ['gold', 'potion', 'trap']
            r.shuffle(contents)
            room['hidden'] = {'chests': contents, 'gold': 10 + idx * 2, 'dmg': 4}
        elif kind == 'trap':
            t = traps[idx % len(traps)] if traps else {'title': 'Ловушка', 'emoji': '⚠️', 'text': '', 'options': ['А', 'Б', 'В']}
            outcomes = list(t.get('outcomes') or ['safe', 'hurt', 'loot'])
            if len(outcomes) != len(t['options']):
                raise ValueError(f"Trap outcomes do not match options: {t['title']}")
            random_choice = 'outcomes' not in t
            if random_choice:
                r.shuffle(outcomes)
            room['trap'] = {'title': t['title'], 'emoji': t['emoji'], 'text': t['text'], 'options': list(t['options']),
                            'image': t.get('image'), 'results': t.get('results') or {}, 'random_choice': random_choice}
            room['hidden'] = {'outcomes': outcomes, 'dmg': 6, 'gold': 8 + idx, 'heal': 8}
        elif kind == 'npc':
            m = r.choice(messages)
            opts = list(players)
            r.shuffle(opts)
            room['npc'] = {'text': (m.get('text') or '')[:200], 'options': opts}
            room['hidden'] = {'answer': opts.index(m['name'])}
        rooms.append(room)

    mp = dict(content.get('mini_pudge') or {'name': 'Мини-Пуджик', 'emoji': '🗿', 'hp': 30, 'atk': 6})
    boss = {'type': 'boss', 'index': BOSS_ROOM, 'flavor': '',
            'enemy': {'name': mp['name'], 'emoji': mp['emoji'], 'hp': mp['hp'] + (4 if rage else 0),
                      'max_hp': mp['hp'] + (4 if rage else 0), 'atk': mp['atk'] + (1 if rage else 0),
                      'intro': mp.get('intro', ''), 'taunts': list(mp.get('taunts') or []), 'bite': mp.get('bite', ''),
                      'image': mp.get('image')}}
    rooms.append(boss)
    rooms[0]['balance_version'] = BALANCE_VERSION
    return rooms


# ── run state ─────────────────────────────────────────────────────────────────
def new_run(seed: str, rooms: list, modifier: str = 'none') -> dict:
    state = {
        'balance_version': rooms[0].get('balance_version', 1), 'history': [],
        'seed': seed, 'step': 0, 'room_index': 0, 'rooms': rooms, 'modifier': modifier,
        'player': dict(BASE_PLAYER), 'phase': 'room', 'room_state': {},
        'log': [], 'chronicle': [], 'rooms_cleared': 0, 'boss_killed': False,
    }
    if modifier == 'prime':
        state['player']['atk'] += 1
    _enter_room(state)
    return state


def _room(state: dict) -> dict:
    return state['rooms'][state['room_index']]


def _log(state: dict, text: str):
    state.setdefault('chronicle', list(state['log'])).append(text)
    state['chronicle'] = state['chronicle'][-100:]
    state['log'].append(text)
    state['log'] = state['log'][-40:]


def _enter_room(state: dict):
    room = _room(state)
    if state['room_index']:
        state.setdefault('chronicle', list(state['log']))
        state['log'] = []
    state['phase'] = 'room'
    state['room_state'] = {}
    if _mod(state) == 'torsion' and state['room_index'] % 2 == 1:
        p = state['player']
        p['hp'] = max(1, p['hp'] - 1)  # the generator hums, never kills outright
        _log(state, "⚙️ Торсионное поле гудит. -1 HP.")
    if room['type'] in ('fight', 'boss'):
        state['room_state'] = {'enemy_hp': room['enemy']['hp'], 'turn': 0, 'atk_bonus': 1 if _mod(state) == 'prime' else 0}
        if room['enemy'].get('intro'):
            _log(state, f"{room['enemy']['emoji']} {room['enemy']['intro']}")
        hp_text = '?' if _mod(state) == 'lowkey' else str(room['enemy']['hp'])
        _log(state, f"{room['enemy']['emoji']} {room['enemy']['name']} — {hp_text} HP, атака {room['enemy']['atk']}.")
    elif room['type'] == 'merchant':
        state['room_state'] = {'bought': []}


def _clear_room(state: dict, text: Optional[str] = None):
    if text:
        _log(state, text)
    state['rooms_cleared'] = max(state['rooms_cleared'], state['room_index'] + 1)
    if state['room_index'] == BOSS_ROOM:
        state['phase'] = 'won'
        state['boss_killed'] = True
    else:
        state['phase'] = 'cleared'


def _hurt(state: dict, dmg: int, text: str) -> bool:
    """Apply damage to the player; returns True if he died."""
    p = state['player']
    if dmg > 0 and p['shield'] > 0:
        p['shield'] -= 1
        _log(state, "🛡️ Щит Капрала принимает удар и рассыпается.")
        return False
    p['hp'] = max(0, p['hp'] - dmg)
    _log(state, text.replace('{hp}', str(p['hp'])))
    if p['hp'] <= 0:
        state['phase'] = 'dead'
        _log(state, "💀 Вы погибли. Данж закрыт до завтра.")
        return True
    return False


def _healing_amount(state: dict, amount: int) -> int:
    return int(amount * 1.3) if _mod(state) == 'no_negativity' else amount


def _heal(state: dict, amount: int) -> int:
    p = state['player']
    amount = _healing_amount(state, amount)
    before = p['hp']
    p['hp'] = min(p['max_hp'], p['hp'] + amount)
    healed = p['hp'] - before
    state['_action_healed'] = state.get('_action_healed', 0) + healed
    return healed


# ── actions available right now ───────────────────────────────────────────────
def available_actions(state: dict, content: dict) -> list:
    phase = state['phase']
    if phase == 'cleared':
        acts = [{'id': 'next', 'label': 'Дальше ➡️'}]
        p = state['player']
        if _new_balance(state) and p['potions'] > 0 and p['hp'] < p['max_hp']:
            acts.insert(0, {'id': 'potion', 'label': f"🧪 Зелье: +{_healing_amount(state, POTION_HEAL)} HP, без атаки врага ({p['potions']})"})
        return acts
    if phase in ('dead', 'won'):
        return []
    room = _room(state)
    p = state['player']
    t = room['type']
    if t in ('fight', 'boss'):
        acts = [{'id': 'attack', 'label': f"⚔️ Удар {p['atk']}–{p['atk'] + 2}"},
                {'id': 'defend', 'label': (f"🛡️ Блок: защита 60%, удар {math.ceil(p['atk'] / 2)}"
                           if _new_balance(state) else '🛡️ Блок: урон по вам ÷2, удар 2')}]
        if not p['special_used']:
            acts.append({'id': 'special', 'label': f"🗿 Статуэтка: {p['atk'] * 2}–{p['atk'] * 2 + 3} урона, раз за заход — без расхода предмета"})
        if p['potions'] > 0:
            acts.append({'id': 'potion', 'label': f"🧪 Зелье: +{_healing_amount(state, POTION_HEAL)} HP, враг ответит ({p['potions']})"})
        return acts
    if t in ('riddle', 'puzzle'):
        return [{'id': f'answer:{i}', 'label': o} for i, o in enumerate(room['riddle']['options'])]
    if t == 'npc':
        return [{'id': f'answer:{i}', 'label': o} for i, o in enumerate(room['npc']['options'])]
    if t == 'treasure':
        return [{'id': f'chest:{i}', 'label': f'📦 Сундук {i + 1}'} for i in range(3)]
    if t == 'trap':
        return [{'id': f'trap:{i}', 'label': o} for i, o in enumerate(room['trap']['options'])]
    if t == 'rest':
        return [{'id': 'rest', 'label': f'🔥 Отдохнуть (+{_healing_amount(state, REST_HEAL)} HP)'}, {'id': 'sharpen', 'label': '🔪 Заточить оружие (+1 атака)'}]
    if t == 'merchant':
        items = (content.get('merchant') or {}).get('items') or {}
        acts = []
        for key, item in items.items():
            acts.append({'id': f'buy:{key}', 'label': f"{item['label']} — {item['price']}💰",
                         'disabled': p['gold'] < item['price']})
        acts.append({'id': 'leave', 'label': '🚪 Уйти'})
        return acts
    return [{'id': 'next', 'label': 'Дальше ➡️'}]


# ── resolve one action ────────────────────────────────────────────────────────
def apply_action(state: dict, action: str, content: dict) -> dict:
    if action not in {a['id'] for a in available_actions(state, content) if not a.get('disabled')}:
        return state
    before = dict(state['player'])
    room_number = state['room_index'] + 1
    state['_action_healed'] = 0
    _apply_action(state, action, content)
    healed = state.pop('_action_healed', 0)
    after = dict(state['player'])
    state.setdefault('history', []).append({
        'step': state['step'], 'room': room_number, 'action': action,
        'balance_version': state.get('balance_version', 1), 'modifier': _mod(state),
        'hp_before': before['hp'], 'hp_after': after['hp'], 'healed': healed,
        'damage_taken': max(0, before['hp'] + healed - after['hp']),
        'gold_before': before['gold'], 'gold_after': after['gold'],
        'potions_before': before['potions'], 'potions_after': after['potions'],
        'phase_after': state['phase'],
    })
    return state


def _apply_action(state: dict, action: str, content: dict) -> dict:
    """Mutates and returns state. Unknown/illegal actions are ignored (no step consumed)."""
    ids = {a['id'] for a in available_actions(state, content) if not a.get('disabled')}
    if action not in ids:
        return state
    state['step'] += 1
    r = _rng(state['seed'], state['step'])
    room = _room(state)
    p = state['player']
    rs = state['room_state']
    t = room['type']

    if action == 'potion' and state['phase'] == 'cleared':
        p['potions'] -= 1
        healed = _heal(state, POTION_HEAL)
        _log(state, f"🧪 Вы пьёте зелье между комнатами: +{healed} HP. Никто не атакует.")
        return state

    if action == 'next':
        state['room_index'] += 1
        _enter_room(state)
        return state

    if t in ('fight', 'boss'):
        enemy = room['enemy']
        player_dmg = 0
        defended = False
        if action == 'attack':
            player_dmg = p['atk'] + r.randint(0, 2)
            crit = r.random() < (0.30 if _mod(state) == 'dai_bozhe' else CRIT_CHANCE)
            if crit:
                player_dmg *= 2
            _log(state, f"⚔️ {enemy['name']} получает {player_dmg} урона{' — КРИТ!' if crit else '.'}")
        elif action == 'special':
            p['special_used'] = True
            player_dmg = p['atk'] * 2 + r.randint(0, 3)
            _log(state, f"🗿 Удар статуэткой Капрала — {player_dmg} урона!")
        elif action == 'defend':
            defended = True
            player_dmg = math.ceil(p['atk'] / 2) if _new_balance(state) else 2
            protection = 60 if _new_balance(state) else 50
            _log(state, f"🛡️ Блок снижает входящий урон на {protection}%. Контрудар: {player_dmg} урона.")
        elif action == 'potion':
            p['potions'] -= 1
            healed = _heal(state, POTION_HEAL)
            _log(state, f"🧪 Фиолетовая жидкость. +{healed} HP (теперь {p['hp']}).")
        rs['enemy_hp'] = max(0, rs['enemy_hp'] - player_dmg)
        if rs['enemy_hp'] <= 0:
            gold = r.randint(4, 8) + room['index']
            if t == 'boss' and _mod(state) == 'old_god':
                gold *= 2
            p['gold'] += gold
            _clear_room(state, f"✅ {enemy['name']} повержен. +{gold} золота.")
            return state
        if _mod(state) == 'sheva' and t == 'fight' and rs['enemy_hp'] <= enemy['max_hp'] * 0.15:
            _clear_room(state, f"🏃 {enemy['name']} ливнул с мида. Как всегда. Золота нет.")
            return state
        # enemy turn
        rs['turn'] += 1
        dmg = enemy['atk'] + rs.get('atk_bonus', 0) + r.randint(-1, 1)
        bite = t == 'boss' and rs['turn'] % (3 if _mod(state) == 'old_god' else 4) == 0
        if bite:
            dmg *= 2
            _log(state, enemy.get('bite') or 'Босс кусает!')
        if defended:
            dmg = (dmg * 2 + 4) // 5 if _new_balance(state) else math.ceil(dmg / 2)
        dmg = max(0, dmg)
        taunts = enemy.get('taunts') or ([enemy['taunt']] if enemy.get('taunt') else [])
        taunt = f" «{r.choice(taunts)}»" if taunts and r.random() < 0.4 else ''
        _hurt(state, dmg, f"💥 {enemy['name']} наносит {dmg} урона.{taunt} У вас {{hp}} HP.")
        return state

    if t in ('riddle', 'puzzle', 'npc') and action.startswith('answer:'):
        i = int(action.split(':', 1)[1])
        correct = i == room['hidden']['answer']
        if correct:
            gold, heal = 6 + room['index'], 4
            p['gold'] += gold
            heal = _heal(state, heal)
            _clear_room(state, f"✅ Верно! +{gold} золота, +{heal} HP.")
        else:
            opts = room['riddle']['options'] if t != 'npc' else room['npc']['options']
            right = opts[room['hidden']['answer']]
            dmg = 5 if t != 'npc' else 3
            if _mod(state) == 'reveal':
                dmg *= 2
            died = _hurt(state, dmg, f"❌ Неверно. Правильно: {right}. Дверь бьёт током: -{dmg} HP.")
            if not died:
                _clear_room(state)
        return state

    if t == 'treasure' and action.startswith('chest:'):
        i = int(action.split(':', 1)[1])
        what = room['hidden']['chests'][i]
        tpl = (content.get('treasure') or {}).get('results') or {}
        if what == 'gold':
            p['gold'] += room['hidden']['gold']
            _clear_room(state, tpl.get('gold', '+{gold}').format(gold=room['hidden']['gold']))
        elif what == 'potion':
            p['potions'] += 1
            _clear_room(state, tpl.get('potion', '+1 зелье'))
        else:
            died = _hurt(state, room['hidden']['dmg'], tpl.get('trap', '-{dmg} HP').format(dmg=room['hidden']['dmg']))
            if not died:
                _clear_room(state)
        return state

    if t == 'trap' and action.startswith('trap:'):
        i = int(action.split(':', 1)[1])
        outcome = room['hidden']['outcomes'][i]
        tpl = dict(content.get('trap_outcomes') or {})
        tpl.update(room['trap'].get('results') or {})
        h = room['hidden']
        if outcome == 'hurt':
            died = _hurt(state, h['dmg'], tpl.get('hurt', '-{dmg} HP').format(dmg=h['dmg']))
            if not died:
                _clear_room(state)
            return state
        if outcome == 'loot':
            p['gold'] += h['gold']
        elif outcome == 'heal':
            actual_heal = _heal(state, h.get('heal', 8))
        elif outcome == 'atk':
            p['atk'] += 1
        elif outcome == 'potion':
            p['potions'] += 1
        elif outcome == 'lose_gold':
            p['gold'] -= p['gold'] // 2
        elif outcome == 'jackpot':
            p['gold'] += max(p['gold'], 5)  # double, or +5 if you came in broke
        text = tpl.get(outcome, tpl.get('safe', 'Пронесло.'))
        _clear_room(state, text.format(gold=(h['gold'] if outcome == 'loot' else p['gold']), dmg=h['dmg'], heal=actual_heal if outcome == 'heal' else h.get('heal', 8)))
        return state

    if t == 'rest':
        if action == 'rest':
            healed = _heal(state, REST_HEAL)
            _clear_room(state, f"🔥 Вы греетесь у костра. +{healed} HP (теперь {p['hp']}).")
        else:
            p['atk'] += 1
            _clear_room(state, f"🔪 Вы точите оружие о статуэтку. Атака {p['atk']}.")
        return state

    if t == 'merchant':
        if action == 'leave':
            _clear_room(state, "🎩 «Заходите ещё, путники». Торговец подмигивает.")
            return state
        key = action.split(':', 1)[1]
        item = ((content.get('merchant') or {}).get('items') or {}).get(key)
        if not item or p['gold'] < item['price']:
            return state
        p['gold'] -= item['price']
        if key == 'potion':
            p['potions'] += 1
        elif key == 'whetstone':
            p['atk'] += 1
        elif key == 'shield':
            p['shield'] = 1
        rs.setdefault('bought', []).append(key)
        _log(state, f"🛒 Куплено: {item['label']}. Цена: {item['price']} золота. Осталось: {p['gold']}.")
        return state

    return state


# ── what the client sees ──────────────────────────────────────────────────────
def public_view(state: dict, content: dict) -> dict:
    room = _room(state)
    t = room['type']
    view_room = {'type': t, 'number': state['room_index'] + 1, 'flavor': room.get('flavor', '')}
    if t in ('fight', 'boss'):
        e = room['enemy']
        image = e.get('image')
        if not image:  # layouts generated before sprites existed: look the image up by name
            if t == 'boss':
                image = (content.get('mini_pudge') or {}).get('image')
            elif e['name'].startswith((content.get('highlight_enemy') or {}).get('name', 'Высер недели')):
                image = (content.get('highlight_enemy') or {}).get('image')
            else:
                image = next((x.get('image') for x in content.get('enemies', []) if x['name'] == e['name']), None)
        view_room.update({
            'warning': ('⚠️ Мини-Пуджик готовится укусить! Следующий удар — двойной. Можно поставить блок.'
                        if _new_balance(state) and t == 'boss' and state['phase'] == 'room'
                        and (state['room_state'].get('turn', 0) + 1) % (3 if _mod(state) == 'old_god' else 4) == 0 else ''),
            'hint': ('🗿 Статуэтка: сильный удар раз за заход. Предмет из инвентаря не тратится.'
                     if not state['player']['special_used'] and state['phase'] == 'room' else ''),
            'title': e['name'], 'emoji': e['emoji'], 'text': e.get('intro', ''), 'image': image,
            'enemy': {'name': e['name'], 'hp': state['room_state'].get('enemy_hp', e['hp']), 'max_hp': e['max_hp'],
                      'atk': e['atk'] + state['room_state'].get('atk_bonus', 0), 'hidden_hp': _mod(state) == 'lowkey'},
        })
    elif t in ('riddle', 'puzzle'):
        pz = content.get('puzzle') or {}
        view_room.update({'title': pz.get('title', 'Загадка'), 'emoji': pz.get('emoji', '🧩'),
                          'text': room['riddle']['q'], 'image': pz.get('image')})
    elif t == 'npc':
        npc = content.get('npc') or {}
        view_room.update({'title': npc.get('title', 'Призрак'), 'emoji': npc.get('emoji', '👻'),
                          'text': npc.get('text', '«{text}»').format(text=room['npc']['text']), 'image': npc.get('image')})
    elif t == 'treasure':
        tr = content.get('treasure') or {}
        view_room.update({'title': tr.get('title', 'Сокровищница'), 'emoji': tr.get('emoji', '💰'), 'text': tr.get('text', ''), 'image': tr.get('image')})
    elif t == 'trap':
        tp = room['trap']
        if tp.get('random_choice'):
            view_room['warning'] = '🎲 Здесь исход случаен: последствия вариантов заранее неизвестны.'
        view_room.update({'title': tp['title'], 'emoji': tp['emoji'], 'text': tp['text'], 'image': tp.get('image') or content.get('trap_image')})
    elif t == 'rest':
        rs = content.get('rest') or {}
        view_room.update({'title': rs.get('title', 'Костёр'), 'emoji': rs.get('emoji', '🔥'), 'text': rs.get('text', ''), 'image': rs.get('image')})
    elif t == 'merchant':
        m = content.get('merchant') or {}
        view_room.update({'title': m.get('title', 'Торговец'), 'emoji': m.get('emoji', '🎩'), 'text': m.get('text', ''), 'image': m.get('image')})
    mods = content.get('modifiers') or {}
    m = mods.get(_mod(state)) or {'name': 'Обычный день', 'desc': ''}
    return {
        'phase': state['phase'],
        'balance_version': state.get('balance_version', 1),
        'modifier': {'key': _mod(state), 'name': m.get('name', ''), 'desc': m.get('desc', '')},
        'room': view_room,
        'rooms_total': ROOMS,
        'rooms_cleared': state['rooms_cleared'],
        'player': dict(state['player']),
        'stats_line': (f"Атака {state['player']['atk']}–{state['player']['atk'] + 2} · крит {int((0.30 if _mod(state) == 'dai_bozhe' else CRIT_CHANCE) * 100)}% (x2)"
                       + (" · 🛡 щит поглотит следующий удар" if state['player']['shield'] else "")),
        'actions': available_actions(state, content),
        'log': state['log'][-25:],
        'chronicle': state.get('chronicle', state['log'])[-100:],
        'boss_killed': state['boss_killed'],
        'map': [{'type': rm['type'], 'done': i < state['rooms_cleared'], 'current': i == state['room_index']}
                for i, rm in enumerate(state['rooms'])],
    }


def is_finished(state: dict) -> bool:
    return state['phase'] in ('dead', 'won')
