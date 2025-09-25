from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime, timedelta
import json
import requests
from icalendar import Calendar
from dateutil import rrule
import os
from threading import Thread
import time
import webbrowser
from dateutil.relativedelta import relativedelta


app = Flask(__name__)
app.secret_key = 'your_key'

TASKS_FILE = 'tasks.json'
BIRTHDAYS_FILE = 'birthdays.json'
MARKS_FILE = 'marks.json'

notifications = []
notification_thread = None
cached_events = []
last_cache_update = None

def load_data():
    tasks = []
    birthdays = {}
    marks = {}
    
    try:
        with open(TASKS_FILE, 'r') as f:
            tasks = json.load(f)
    except FileNotFoundError:
        pass
        
    try:
        with open(BIRTHDAYS_FILE, 'r') as f:
            birthdays_data = json.load(f)
            for date, name in birthdays_data.items():
                if isinstance(name, list):
                    birthdays[date] = name
                else:
                    birthdays[date] = [name]
    except FileNotFoundError:
        pass
        
    try:
        with open(MARKS_FILE, 'r') as f:
            marks_data = json.load(f)
            for date, text in marks_data.items():
                if isinstance(text, list):
                    marks[date] = text
                else:
                    marks[date] = [text]
    except FileNotFoundError:
        pass
        
    for i, task in enumerate(tasks):
        if 'id' not in task:
            task['id'] = i + 1
    
    return tasks, birthdays, marks

def save_data(tasks, birthdays, marks):
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)
    with open(BIRTHDAYS_FILE, 'w') as f:
        json.dump(birthdays, f, indent=2)
    with open(MARKS_FILE, 'w') as f:
        json.dump(marks, f, indent=2)

def load_schedule():
    global cached_events, last_cache_update
    
    if cached_events and last_cache_update and (datetime.now() - last_cache_update).seconds < 3600:
        return cached_events
    
    events = []
    try:
        url = "your_url"
        response = requests.get(url, timeout=30)
        calendar = Calendar.from_ical(response.content)
        
        now = datetime.now()
        start_date = now - relativedelta(months=2)
        end_date = now + relativedelta(years=1)
        
        print(f"Загрузка событий с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}")
        
        for component in calendar.walk():
            if component.name == "VEVENT":
                summary = str(component.get('summary', 'Без названия'))
                description = str(component.get('description', ''))
                location = str(component.get('location', ''))
                
                start_dt = component.get('dtstart').dt
                if hasattr(start_dt, 'date'):
                    start_date_only = start_dt.date()
                else:
                    start_date_only = start_dt
                
                end_dt = component.get('dtend').dt
                if hasattr(end_dt, 'date'):
                    end_date_only = end_dt.date()
                else:
                    end_date_only = end_dt
                
                if start_date_only > end_date.date() or end_date_only < start_date.date():
                    continue
                
                if hasattr(start_dt, 'strftime'):
                    start_str = start_dt.strftime('%d.%m.%Y %H:%M')
                else:
                    start_str = start_dt.strftime('%d.%m.%Y')
                    
                if hasattr(end_dt, 'strftime'):
                    end_str = end_dt.strftime('%d.%m.%Y %H:%M')
                else:
                    end_str = end_dt.strftime('%d.%m.%Y')
                
                rrule_data = component.get('rrule')
                if rrule_data:
                    try:
                        rule = rrule.rrulestr(rrule_data.to_ical().decode('utf-8'), dtstart=start_dt)
                        occurrences = list(rule.between(start_date, end_date))
                        
                        for occ in occurrences:
                            occ_start_str = occ.strftime('%d.%m.%Y %H:%M')
                            
                            if hasattr(start_dt, 'hour') and hasattr(end_dt, 'hour'):
                                duration = end_dt - start_dt
                                occ_end = occ + duration
                                occ_end_str = occ_end.strftime('%d.%m.%Y %H:%M')
                            else:
                                occ_end_str = end_str
                            
                            events.append({
                                'start': occ_start_str,
                                'end': occ_end_str,
                                'summary': summary,
                                'description': description,
                                'location': location,
                                'is_recurring': True
                            })
                    except Exception as e:
                        print(f"Ошибка обработки повторяющегося события: {e}")
                        events.append({
                            'start': start_str,
                            'end': end_str,
                            'summary': summary,
                            'description': description,
                            'location': location,
                            'is_recurring': False
                        })
                else:
                    events.append({
                        'start': start_str,
                        'end': end_str,
                        'summary': summary,
                        'description': description,
                        'location': location,
                        'is_recurring': False
                    })
        
        print(f"Загружено {len(events)} событий")
        cached_events = events
        last_cache_update = datetime.now()
        
    except Exception as e:
        print(f"Ошибка загрузки расписания: {e}")
        import traceback
        traceback.print_exc()

    return events

def check_upcoming_events():
    global notifications
    while True:
        try:
            tasks, birthdays, marks = load_data()
            events = load_schedule()
            today = datetime.now().date()
            new_notifications = []
            
            for task in tasks:
                if not task.get('completed', False):
                    try:
                        deadline = datetime.strptime(task['deadline'], '%d.%m.%Y').date()
                        days_until = (deadline - today).days
                        if 0 <= days_until <= 3:
                            new_notifications.append({
                                'type': 'task',
                                'message': f'Задача "{task["description"]}" должна быть выполнена через {days_until} дн.',
                                'date': task['deadline']
                            })
                    except:
                        pass
            
            tomorrow = today + timedelta(days=1)
            for event in events:
                try:
                    event_date_str = event['start'].split(' ')[0]
                    event_date = datetime.strptime(event_date_str, '%d.%m.%Y').date()
                    if event_date == tomorrow:
                        new_notifications.append({
                            'type': 'event',
                            'message': f'Завтра событие: {event["summary"]}',
                            'date': event_date_str
                        })
                except:
                    pass
            
            for i in range(7):
                check_date = today + timedelta(days=i)
                bd_key = check_date.strftime('%d.%m')
                if bd_key in birthdays:
                    names = birthdays[bd_key]
                    if not isinstance(names, list):
                        names = [names]
                    
                    for name in names:
                        if i == 0:
                            new_notifications.append({
                                'type': 'birthday',
                                'message': f'Сегодня день рождения у {name}!',
                                'date': check_date.strftime('%d.%m.%Y')
                            })
                        else:
                            new_notifications.append({
                                'type': 'birthday',
                                'message': f'Через {i} дн. день рождения у {name}',
                                'date': check_date.strftime('%d.%m.%Y')
                            })
            
            notifications = new_notifications
        except Exception as e:
            print(f"Ошибка в проверке уведомлений: {e}")
        
        time.sleep(3600)

@app.route('/')
def index():
    week_offset = session.get('week_offset', 0)
    
    tasks, birthdays, marks = load_data()
    events = load_schedule()
    
    incomplete_tasks = [t for t in tasks if not t.get('completed', False)]
    complete_tasks = [t for t in tasks if t.get('completed', False)]
    
    try:
        incomplete_tasks.sort(key=lambda x: datetime.strptime(x['deadline'], '%d.%m.%Y'))
    except:
        pass
    
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = []
    
    for i in range(7):
        day_date = week_start + timedelta(days=i)
        day_events = []
        
        for event in events:
            event_date_str = event['start'].split(' ')[0]
            try:
                event_date = datetime.strptime(event_date_str, '%d.%m.%Y').date()
                if event_date == day_date:
                    day_events.append(event)
            except:
                pass
        
        bd_key = day_date.strftime('%d.%m')
        day_birthdays = []
        if bd_key in birthdays:
            names = birthdays[bd_key]
            if not isinstance(names, list):
                names = [names]
            for name in names:
                day_birthdays.append({
                    'date': bd_key,
                    'name': name
                })
        
        date_key = day_date.strftime('%d.%m.%Y')
        day_marks = []
        if date_key in marks:
            texts = marks[date_key]
            if not isinstance(texts, list):
                texts = [texts]
            for text in texts:
                day_marks.append({
                    'date': date_key,
                    'text': text
                })
        
        week_days.append({
            'date': day_date,
            'date_str': day_date.strftime('%d.%m.%Y'),
            'day_name': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'][i],
            'events': day_events,
            'birthdays': day_birthdays,
            'marks': day_marks
        })
    
    return render_template('index.html', 
                         tasks=incomplete_tasks + complete_tasks,
                         week_days=week_days,
                         today=today.strftime('%d.%m.%Y'),
                         week_offset=week_offset,
                         notifications=notifications,
                         birthdays=birthdays,
                         marks=marks)

@app.route('/prev_week', methods=['POST'])
def prev_week():
    current_offset = session.get('week_offset', 0)
    session['week_offset'] = current_offset - 1
    return redirect(url_for('index'))

@app.route('/next_week', methods=['POST'])
def next_week():
    current_offset = session.get('week_offset', 0)
    session['week_offset'] = current_offset + 1
    return redirect(url_for('index'))

@app.route('/current_week', methods=['POST'])
def current_week():
    session['week_offset'] = 0
    return redirect(url_for('index'))

@app.route('/add_task', methods=['POST'])
def add_task():
    description = request.form.get('description')
    deadline = request.form.get('deadline')
    
    if description and deadline:
        try:
            datetime.strptime(deadline, '%d.%m.%Y')
        except ValueError:
            return "Неверный формат даты. Используйте ДД.ММ.ГГГГ", 400
        
        tasks, birthdays, marks = load_data()
        task_id = max([t.get('id', 0) for t in tasks]) + 1 if tasks else 1
        tasks.append({
            'id': task_id,
            'description': description,
            'deadline': deadline,
            'completed': False
        })
        save_data(tasks, birthdays, marks)
    
    return redirect(url_for('index'))

@app.route('/toggle_task/<int:task_id>')
def toggle_task(task_id):
    tasks, birthdays, marks = load_data()
    
    for task in tasks:
        if task.get('id') == task_id:
            task['completed'] = not task.get('completed', False)
            break
    
    save_data(tasks, birthdays, marks)
    return redirect(url_for('index'))

@app.route('/delete_task/<int:task_id>')
def delete_task(task_id):
    tasks, birthdays, marks = load_data()
    tasks = [t for t in tasks if t.get('id') != task_id]
    save_data(tasks, birthdays, marks)
    return redirect(url_for('index'))

@app.route('/add_birthday', methods=['POST'])
def add_birthday():
    date = request.form.get('date')
    name = request.form.get('name')
    
    if date and name:
        try:
            datetime.strptime(date + '.2000', '%d.%m.%Y')
        except ValueError:
            return "Неверный формат даты. Используйте ДД.ММ", 400
        
        tasks, birthdays, marks = load_data()
        if date in birthdays:
            if isinstance(birthdays[date], list):
                birthdays[date].append(name)
            else:
                birthdays[date] = [birthdays[date], name]
        else:
            birthdays[date] = [name]
        save_data(tasks, birthdays, marks)
    
    return redirect(url_for('index'))

@app.route('/delete_birthday/<date>')

def delete_birthday(date):
    tasks, birthdays, marks = load_data()
    if date in birthdays:
        if isinstance(birthdays[date], list) and len(birthdays[date]) > 1:
            birthdays[date].pop(0)
            if len(birthdays[date]) == 1:
                birthdays[date] = birthdays[date][0]
        else:
            del birthdays[date]
        save_data(tasks, birthdays, marks)
    return redirect(url_for('index'))

@app.route('/delete_specific_birthday/<date>/<name>')
def delete_specific_birthday(date, name):
    tasks, birthdays, marks = load_data()
    if date in birthdays:
        if isinstance(birthdays[date], list):
            if name in birthdays[date]:
                birthdays[date].remove(name)
                if len(birthdays[date]) == 0:
                    del birthdays[date]
                elif len(birthdays[date]) == 1:
                    birthdays[date] = birthdays[date][0]
        else:
            if birthdays[date] == name:
                del birthdays[date]
        save_data(tasks, birthdays, marks)
    return redirect(url_for('index'))

@app.route('/add_mark', methods=['POST'])
def add_mark():
    date = request.form.get('date')
    text = request.form.get('text')
    
    if date and text:
        try:
            datetime.strptime(date, '%d.%m.%Y')
        except ValueError:
            return "Неверный формат даты. Используйте ДД.ММ.ГГГГ", 400
        
        tasks, birthdays, marks = load_data()
        if date in marks:
            if isinstance(marks[date], list):
                marks[date].append(text)
            else:
                marks[date] = [marks[date], text]
        else:
            marks[date] = [text]
        save_data(tasks, birthdays, marks)
    
    return redirect(url_for('index'))

@app.route('/delete_mark/<date>')
def delete_mark(date):
    tasks, birthdays, marks = load_data()
    if date in marks:
        if isinstance(marks[date], list) and len(marks[date]) > 1:
            marks[date].pop(0)
            if len(marks[date]) == 1:
                marks[date] = marks[date][0]
        else:
            del marks[date]
        save_data(tasks, birthdays, marks)
    return redirect(url_for('index'))

@app.route('/delete_specific_mark/<date>/<text>')
def delete_specific_mark(date, text):
    tasks, birthdays, marks = load_data()
    if date in marks:
        if isinstance(marks[date], list):
            if text in marks[date]:
                marks[date].remove(text)
                if len(marks[date]) == 0:
                    del marks[date]
                elif len(marks[date]) == 1:
                    marks[date] = marks[date][0]
        else:
            if marks[date] == text:
                del marks[date]
        save_data(tasks, birthdays, marks)
    return redirect(url_for('index'))

@app.route('/clear_notifications')
def clear_notifications():
    global notifications
    notifications = []
    return redirect(url_for('index'))

@app.route('/refresh_schedule')
def refresh_schedule():
    global cached_events, last_cache_update
    cached_events = []
    last_cache_update = None
    return redirect(url_for('index'))

def create_template():
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    with open('templates/index.html', 'w', encoding='utf-8') as f:
        f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>Календарь с задачами</title>
    <meta charset="UTF-8">
    <style>
        :root {
            --bg-color: #1e1e1e;
            --text-color: #e0e0e0;
            --accent-color: #bb86fc;
            --secondary-color: #03dac6;
            --card-bg: #2d2d2d;
            --border-color: #444;
        }
        
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0; 
            padding: 20px; 
            background-color: var(--bg-color);
            color: var(--text-color);
        }
        
        .container { 
            display: flex; 
            gap: 20px;
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .sidebar { 
            width: 350px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        
        .calendar { 
            flex: 1; 
        }
        
        .card {
            background: var(--card-bg);
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        h1, h2, h3 {
            color: var(--accent-color);
            margin-top: 0;
        }
        
        .task { 
            padding: 10px; 
            border-bottom: 1px solid var(--border-color); 
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .task:hover {
            background: rgba(255, 255, 255, 0.05);
        }
        
        .task.completed { 
            text-decoration: line-through; 
            color: #888; 
        }
        
        .task-actions {
            display: flex;
            gap: 10px;
        }
        
        .day { 
            margin-bottom: 20px; 
            border: 1px solid var(--border-color); 
            border-radius: 8px;
            padding: 15px;
            background: var(--card-bg);
        }
        
        .day-header { 
            font-weight: bold; 
            margin-bottom: 10px; 
            color: var(--secondary-color);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 5px;
        }
        
        .event { 
            margin: 8px 0; 
            padding: 8px; 
            background: rgba(255, 255, 255, 0.05);
            border-radius: 5px;
        }
        
        .recurring-event {
            border-left: 3px solid var(--accent-color);
        }
        
        form { 
            margin: 10px 0; 
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        
        input, textarea, button { 
            padding: 10px; 
            border: 1px solid var(--border-color);
            border-radius: 5px;
            background: var(--card-bg);
            color: var(--text-color);
        }
        
        button {
            background: var(--accent-color);
            color: #000;
            border: none;
            cursor: pointer;
            font-weight: bold;
        }
        
        button:hover {
            opacity: 0.9;
        }
        
        .delete-btn {
            background: #cf6679;
            color: white;
            padding: 5px 10px;
            font-size: 12px;
        }
        
        .week-nav {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
            align-items: center;
        }
        
        .week-nav form {
            display: flex;
            gap: 10px;
            margin: 0;
        }
        
        .week-title {
            font-size: 1.5em;
            font-weight: bold;
        }
        
        .notifications {
            margin-bottom: 20px;
        }
        
        .notification {
            padding: 10px;
            margin: 5px 0;
            background: rgba(3, 218, 198, 0.2);
            border-left: 4px solid var(--secondary-color);
            border-radius: 4px;
        }
        
        .clear-notifications {
            background: var(--secondary-color);
            color: #000;
            margin-top: 10px;
        }
        
        .birthday-item, .mark-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px;
            margin: 5px 0;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 5px;
        }
        
        .empty-message {
            padding: 10px;
            color: #888;
            font-style: italic;
            text-align: center;
        }
        
        .refresh-btn {
            background: var(--secondary-color);
            color: #000;
            margin-left: 10px;
        }
        
        .date-hint {
            font-size: 0.8em;
            color: #888;
            margin-top: -8px;
        }
        
        .today-btn {
            background: var(--secondary-color);
            color: #000;
            padding: 5px 10px;
            font-size: 12px;
            margin-left: 5px;
        }
        
        .multiple-items {
            border-left: 3px solid var(--secondary-color);
        }
    </style>
</head>
<body>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
        <h1>Календарь с задачами</h1>
        <a href="{{ url_for('refresh_schedule') }}"><button class="refresh-btn">🔄 Обновить расписание</button></a>
    </div>
    
    <div class="week-nav">
        <div>
            <form action="{{ url_for('prev_week') }}" method="post" style="display: inline;">
                <button type="submit">← Предыдущая неделя</button>
            </form>
            <form action="{{ url_for('current_week') }}" method="post" style="display: inline;">
                <button type="submit">Текущая неделя</button>
            </form>
            <form action="{{ url_for('next_week') }}" method="post" style="display: inline;">
                <button type="submit">Следующая неделя →</button>
            </form>
        </div>
        <div class="week-title">
            {% if week_offset == 0 %}
                Текущая неделя
            {% elif week_offset > 0 %}
                Через {{ week_offset }} недель(и)
            {% else %}
                {{ -week_offset }} недель(и) назад
            {% endif %}
        </div>
    </div>
    
    {% if notifications %}
    <div class="notifications card">
        <h3>🔔 Уведомления</h3>
        {% for notification in notifications %}
        <div class="notification">
            {{ notification.message }}
        </div>
        {% endfor %}
        <a href="{{ url_for('clear_notifications') }}"><button class="clear-notifications">Очистить уведомления</button></a>
    </div>
    {% endif %}
    
    <div class="container">
        <div class="sidebar">
            <div class="card">
                <h2>Задачи</h2>
                
                <form action="{{ url_for('add_task') }}" method="post">
                    <input type="text" name="description" placeholder="Описание задачи" required>
                    <div style="display: flex; align-items: center;">
                        <input type="text" name="deadline" id="deadline" placeholder="ДД.ММ.ГГГГ" required style="flex: 1;">
                        <button type="button" class="today-btn" onclick="setToday('deadline')">Сегодня</button>
                    </div>
                    <div class="date-hint">Формат: ДД.ММ.ГГГГ (например, 25.12.2024)</div>
                    <button type="submit">Добавить задачу</button>
                </form>
                
                <div id="task-list">
                    {% for task in tasks %}
                    <div class="task {% if task.completed %}completed{% endif %}">
                        <span onclick="location.href='{{ url_for('toggle_task', task_id=task.id) }}'">
                            {{ task.deadline }} - {{ task.description }}
                        </span>
                        <div class="task-actions">
                            <a href="{{ url_for('delete_task', task_id=task.id) }}" onclick="return confirm('Удалить задачу?')">
                                <button class="delete-btn">✕</button>
                            </a>
                        </div>
                    </div>
                    {% else %}
                    <div class="empty-message">Нет задач</div>
                    {% endfor %}
                </div>
            </div>
            
            <div class="card">
                <h3>Дни рождения</h3>
                <form action="{{ url_for('add_birthday') }}" method="post">
                    <input type="text" name="date" id="birthday-date" placeholder="ДД.ММ" required>
                    <input type="text" name="name" placeholder="Имя" required>
                    <div class="date-hint">Формат: ДД.ММ (например, 25.12)</div>
                    <button type="submit">Добавить</button>
                </form>
                
                {% for bd_date, names in birthdays.items() %}
                    {% if names is string %}
                    <div class="birthday-item">
                        <span>{{ bd_date }} - {{ names }}</span>
                        <a href="{{ url_for('delete_birthday', date=bd_date) }}" onclick="return confirm('Удалить день рождения?')">
                            <button class="delete-btn">✕</button>
                        </a>
                    </div>
                    {% else %}
                        {% for name in names %}
                        <div class="birthday-item multiple-items">
                            <span>{{ bd_date }} - {{ name }}</span>
                            <a href="{{ url_for('delete_specific_birthday', date=bd_date, name=name) }}" onclick="return confirm('Удалить день рождения?')">
                                <button class="delete-btn">✕</button>
                            </a>
                        </div>
                        {% endfor %}
                    {% endif %}
                {% else %}
                <div class="empty-message">Нет дней рождения</div>
                {% endfor %}
            </div>
            
            <div class="card">
                <h3>Метки</h3>
                <form action="{{ url_for('add_mark') }}" method="post">
                    <input type="text" name="date" id="mark-date" placeholder="ДД.ММ.ГГГГ" required>
                    <input type="text" name="text" placeholder="Текст метки" required>
                    <div style="display: flex; align-items: center;">
                        <div style="flex: 1;">
                            <div class="date-hint">Формат: ДД.ММ.ГГГГ (например, 25.12.2024)</div>
                        </div>
                        <button type="button" class="today-btn" onclick="setToday('mark-date')">Сегодня</button>
                    </div>
                    <button type="submit">Добавить</button>
                </form>
                
                {% for mark_date, texts in marks.items() %}
                    {% if texts is string %}
                    <div class="mark-item">
                        <span>{{ mark_date }} - {{ texts }}</span>
                        <a href="{{ url_for('delete_mark', date=mark_date) }}" onclick="return confirm('Удалить метку?')">
                            <button class="delete-btn">✕</button>
                        </a>
                    </div>
                    {% else %}
                        {% for text in texts %}
                        <div class="mark-item multiple-items">
                            <span>{{ mark_date }} - {{ text }}</span>
                            <a href="{{ url_for('delete_specific_mark', date=mark_date, text=text) }}" onclick="return confirm('Удалить метку?')">
                                <button class="delete-btn">✕</button>
                            </a>
                        </div>
                        {% endfor %}
                    {% endif %}
                {% else %}
                <div class="empty-message">Нет меток</div>
                {% endfor %}
            </div>
        </div>
        
        <div class="calendar">
            <h2>Расписание на неделю</h2>
            {% for day in week_days %}
            <div class="day">
                <div class="day-header">
                    {{ day.date_str }} ({{ day.day_name }}) 
                    {% if day.date_str == today %} 
                        <span style="color: var(--secondary-color);">- СЕГОДНЯ</span> 
                    {% endif %}
                </div>
                
                {% for event in day.events %}
                <div class="event {% if event.is_recurring %}recurring-event{% endif %}">
                    <strong>📚 {{ event.summary }}</strong><br>
                    <small>🕒 {{ event.start }} - {{ event.end }}</small>
                    {% if event.location %}
                    <br><small>📍 {{ event.location }}</small>
                    {% endif %}
                    {% if event.is_recurring %}
                    <br><small>🔄 Повторяющееся событие</small>
                    {% endif %}
                </div>
                {% endfor %}
                
                {% for birthday in day.birthdays %}
                <div class="event">🎂 {{ birthday.name }} (день рождения)</div>
                {% endfor %}
                
                {% for mark in day.marks %}
                <div class="event">📍 {{ mark.text }}</div>
                {% endfor %}
                
                {% if not day.events and not day.birthdays and not day.marks %}
                <div class="empty-message">Нет событий</div>
                {% endif %}
            </div>
            {% endfor %}
        </div>
    </div>
    
    <script>
        function formatDateInput(input, format) {
            let digits = input.value.replace(/[^\d]/g, '');

            if (format === 'dd.mm') {
                if (digits.length > 2) {
                    digits = digits.substring(0, 2) + '.' + digits.substring(2, 4);
                }
                if (digits.length > 5) {
                    digits = digits.substring(0, 5);
                }
                input.value = digits;
            } else {
                if (digits.length > 2) {
                    digits = digits.substring(0, 2) + '.' + digits.substring(2);
                }
                if (digits.length > 5) {
                    digits = digits.substring(0, 5) + '.' + digits.substring(5);
                }
                if (digits.length > 10) {
                    digits = digits.substring(0, 10);
                }
                input.value = digits;
            }
        }
        
        document.getElementById('deadline')?.addEventListener('input', function() {
            formatDateInput(this, 'dd.mm.yyyy');
        });
        
        document.getElementById('mark-date')?.addEventListener('input', function() {
            formatDateInput(this, 'dd.mm.yyyy');
        });
        
        document.getElementById('birthday-date')?.addEventListener('input', function() {
            formatDateInput(this, 'dd.mm');
        });
        
        function setToday(fieldId) {
            const today = new Date();
            const day = String(today.getDate()).padStart(2, '0');
            const month = String(today.getMonth() + 1).padStart(2, '0');
            const year = today.getFullYear();
            
            const dateField = document.getElementById(fieldId);
            if (fieldId === 'birthday-date') {
                dateField.value = `${day}.${month}`;
            } else {
                dateField.value = `${day}.${month}.${year}`;
            }
        }
        
        document.querySelectorAll('input[type="text"]').forEach(input => {
            input.addEventListener('focus', function() {
                this.style.borderColor = 'var(--accent-color)';
            });
            
            input.addEventListener('blur', function() {
                this.style.borderColor = 'var(--border-color)';
            });
        });
    </script>
</body>
</html>
        ''')

if __name__ == '__main__':
    create_template()
    
    notification_thread = Thread(target=check_upcoming_events, daemon=True)
    notification_thread.start()
    
    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')
    
    Thread(target=open_browser, daemon=True).start()
    
    app.run(debug=True, port=5000, use_reloader=False)
