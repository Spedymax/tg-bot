"""Tool definitions offered to the persona model (shared by the bot and evals)."""

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Поиск в интернете. Вызывай, когда нужен свежий или точный факт, которого ты "
            "не знаешь: новости, курсы, результаты матчей, кто такой X, что за X, что случилось. "
            "Любой вопрос про незнакомого человека/вещь/событие — повод искать, а не отвечать «хз». "
            "На болтовню, мнения и советы поиск не нужен. Прозвища, внутряки, опечатки и "
            "слова из этого чата не ищи — сначала смотри историю и память чата."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Короткий поисковый запрос на русском (или на языке темы).",
                },
                "reason": {
                    "type": "string",
                    "enum": ["freshness", "unknown_entity", "verification", "explicit_request"],
                    "description": "Почему нужен поиск: свежие данные, незнакомая сущность, "
                                   "проверка факта или тебя прямо попросили поискать.",
                },
            },
            "required": ["query"],
        },
    },
}
