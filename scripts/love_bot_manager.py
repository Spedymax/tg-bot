from flask import Flask, request
import git
import subprocess
import time
from threading import Thread

app = Flask(__name__)

main_process = None  # Переменная для хранения процесса love.py

def start_main_script():
    """Запускает love.py и возвращает объект процесса."""
    global main_process
    if main_process is None or main_process.poll() is not None:
        print("Запуск love.py...")
        main_process = subprocess.Popen(['/home/spedymax/venv/bin/python3', '/home/spedymax/tg-bot/scripts/love.py'])

def restart_main_script():
    """Перезапускает love.py."""
    global main_process
    if main_process:
        print("Останавливаю love.py...")
        main_process.terminate()
        main_process.wait()  # Ожидание завершения
    start_main_script()  # Перезапуск love.py

@app.route('/update_love', methods=['POST'])
def update_repo():
    """Обрабатывает вебхук от GitHub для обновления репозитория и перезапуска love.py."""
    print("Получен POST-запрос на обновление (love).")
    if request.method == 'POST':
        repo_path = '/home/spedymax/tg-bot'  # Полный путь к репозиторию
        try:
            repo = git.Repo(repo_path)
            print("Выполняю git pull с rebase...")
            try:
                repo.git.pull('--rebase')  # Попытка выполнить pull с rebase
            except git.GitCommandError as e:
                if 'unable to update local ref' in str(e):
                    print("Обнаружен конфликт refs/remotes/origin/main. Пробую сбросить изменения...")
                    repo.git.fetch('--all')
                    repo.git.reset('--hard', 'origin/main')  # Жёсткий сброс на удалённую ветку
                    print("Локальные изменения сброшены. Обновление завершено.")
                else:
                    raise e  # Если ошибка другая, выбрасываем её

            print("Репозиторий успешно обновлен. Перезапуск love.py...")
            restart_main_script()  # Перезапускаем love.py после обновления
            return 'Репозиторий обновлен и love.py перезапущен.', 200
        except Exception as e:
            print(f"Ошибка обновления репозитория: {e}")
            return f"Ошибка обновления репозитория: {e}", 500

def main_loop():
    """Постоянно проверяет состояние love.py и перезапускает его при падении."""
    while True:
        try:
            start_main_script()  # Запускаем, если не запущено
            time.sleep(5)  # Проверяем каждые 5 секунд
        except Exception as e:
            print(f"Ошибка в main_loop: {e}")
            time.sleep(15)  # Ждем перед повторной попыткой

if __name__ == '__main__':
    # Запускаем Flask в отдельном потоке
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=5005))
    flask_thread.start()

    # Запускаем проверку на падение love.py
    main_loop()
