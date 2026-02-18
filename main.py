import asyncio
import aiohttp
import requests
import time
import json
import os
import base64
import re
import smtplib
import signal
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase.ttfonts import TTFont
from aiohttp import web

# Загрузка переменных окружения
load_dotenv()

# Информация о заявителе
APPLICANT_BIRTH = os.getenv('APPLICANT_BIRTH')
SERIES = os.getenv('SERIES')
NUMBER = os.getenv('NUMBER')
APPLICANT_RES_ADDRESS = os.getenv('APPLICANT_RES_ADDRESS')
APPLICANT_INN = os.getenv('APPLICANT_INN')
APPLICANT_OGRNIP = os.getenv('APPLICANT_OGRNIP')
OGRNIP_BIRTH = os.getenv('OGRNIP_BIRTH')
APPLICANT_PHONE = os.getenv('APPLICANT_PHONE')
APPLICANT_EMAIL = os.getenv('APPLICANT_EMAIL')

# Настройки
API_URL = 'https://api-cloud.ru/api/bankrot.php'
TOKEN = os.getenv('API_TOKEN')
TRUSTEE_NAMES = [
    'Мурдашева Алсу Ишбулатновна',
    'Калашникова Наталья Александровна',
    'Закиров Тимур Назифович',
    'Фамиев Ильнур Илдусович',
    'Галеева Алина Рифмеровна',
    'Тихонова Кристина Александровна'
]
SEEN_FILE = 'seen_cases.json'
PENDING_LOTS_FILE = 'pending_lots.json'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
EMAIL_FROM = os.getenv('EMAIL_FROM')
EMAIL = os.getenv('EMAIL')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
EMAIL_TO = os.getenv('EMAIL_TO')
SMTP_SERVER = 'connect.smtp.bz'
SMTP_PORT = 587
TIMEOUT = 120  

# Глобальные переменные для состояния
seen_cases = []
pending_lots = []
monitoring_task = None
is_running = True

# Функция для загрузки просмотренных дел
def load_seen_cases():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            return json.load(f)
    return []

# Функция для сохранения просмотренных дел
def save_seen_cases(cases):
    with open(SEEN_FILE, 'w') as f:
        json.dump(cases, f)

# Функция для загрузки ожидающих лотов
def load_pending_lots():
    if os.path.exists(PENDING_LOTS_FILE):
        try:
            with open(PENDING_LOTS_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []

# Функция для сохранения ожидающих лотов
def save_pending_lots(lots):
    with open(PENDING_LOTS_FILE, 'w') as f:
        json.dump(lots, f)

# Функция для поиска дел по управляющему
def search_cases(trustee_name):
    params = {
        'type': 'searchString',
        'string': trustee_name,
        'legalStatus': 'legal',
        'token': TOKEN
    }
    try:
        response = requests.get(API_URL, params=params, timeout=120)
        data = response.json()
        if 'rez' in data:
            return data['rez']
        else:
            return []
    except Exception as e:
        return []

# Функция для получения подробной информации по делу
def get_case_details(guid):
    params = {
        'type': 'search',
        'guid': guid,
        'legalStatus': 'legal',
        'token': TOKEN
    }
    try:
        response = requests.get(API_URL, params=params, timeout=120)
        return response.json()
    except Exception as e:
        return None

# Асинхронная функция для поиска дел по управляющему
async def search_cases_async(session, trustee_name):
    params = {
        'type': 'searchString',
        'string': trustee_name,
        'legalStatus': 'legal',
        'token': TOKEN
    }
    try:
        async with session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=120)) as response:
            data = await response.json()
            if 'rez' in data:
                return data['rez']
            else:
                return []
    except Exception as e:
        return []

# Асинхронная функция для получения подробной информации по делу
async def get_case_details_async(session, guid):
    params = {
        'type': 'search',
        'guid': guid,
        'legalStatus': 'legal',
        'token': TOKEN
    }
    try:
        async with session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=120)) as response:
            return await response.json()
    except Exception as e:
        return None

async def send_to_telegram(message, docx_path=None):
    print(f"Отправка сообщения в Telegram: {message}")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
            print("✓ Сообщение отправлено в Telegram")
            if docx_path and os.path.exists(docx_path):
                document = FSInputFile(docx_path, filename=os.path.basename(docx_path))
                await bot.send_document(chat_id=TELEGRAM_CHAT_ID, document=document)
                print("✓ DOCX отправлен в Telegram")
        except TelegramBadRequest as e:
            print(f"✗ Ошибка отправки в Telegram: {e}")
    else:
        print("✗ Переменные Telegram не установлены, пропуск отправки")

# Функция для генерации PDF
def generate_pdf(trustee_name, case_info):
    from datetime import datetime
    
    # Извлечение данных из case_info
    debtor_name = case_info.get('debtorName', {}).get('value', 'ФИО')
    property_desc = case_info.get('description', {}).get('value', 'Имущество').replace('Имущество: ', '')
    
    # Проверяем наличие файла подписи
    img = None
    if os.path.exists("sign.png"):
        img = Image("sign.png", width=3*cm, height=1*cm)

    # Извлечение минимальной цены из описания имущества
    match = re.search(r'начальная цена (\d+)', property_desc)
    if match:
        min_price = int(match.group(1))
    else:
        min_price = 0

    bid_price = min_price + 1000

    # Текущая дата
    now = datetime.now()
    day = now.day
    month_num = int(now.strftime('%m'))
    month_names = ['Января', 'Февраля', 'Марта', 'Апреля', 'Мая', 'Июня', 'Июля', 'Августа', 'Сентября', 'Октября', 'Ноября', 'Декабря']
    month = month_names[month_num - 1]
    year = now.year

    # Создание PDF
    filename = f"Заявка_{case_info.get('lastLegalCasenNumber', {}).get('value', 'N/A')}.pdf"
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        title="Заявка",
        author="ИП Хисматовой Э.В.",
        subject="Заявка на участие в торгах",    
        creator="User")
    
    styles = getSampleStyleSheet()

    # Попытка зарегистрировать SF Pro шрифт (если доступен)
    try:
        pdfmetrics.registerFont(TTFont('SFProText-Regular', 'SFProText-Regular.ttf'))
        font_name = 'SFProText-Regular'
    except:
        font_name = 'Helvetica'

    # Стили для выравнивания
    style_right = ParagraphStyle('right', parent=styles['Normal'], alignment=TA_RIGHT, fontName=font_name)
    style_center = ParagraphStyle('center', parent=styles['Normal'], alignment=TA_CENTER, fontName=font_name)
    style_left = ParagraphStyle('left', parent=styles['Normal'], alignment=TA_LEFT, fontName=font_name)

    story = []

    # Содержимое заявки
    story.append(Paragraph('Финансовому управляющему', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph('Окунев Алексей Викторович', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph('От ИП Хисматовой Э.В.', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph(f'ОГРНИП: {APPLICANT_OGRNIP}', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph(f'ИНН: {APPLICANT_INN}, Дата присвоения', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph(f'ОГРНИП: {OGRNIP_BIRTH}', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph('зарегистрированного по адресу:', style_right))
    story.append(Spacer(1, 5))
    story.append(Paragraph(f'{APPLICANT_RES_ADDRESS}', style_right))
    story.append(Spacer(1, 80))
    story.append(Paragraph('Заявка на участие в торгах', style_center))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f'Я, ИП Хисматова Эльвира Валерьяновна {APPLICANT_BIRTH} г.р, паспорт {SERIES} {NUMBER}, подаю настоящую заявку на приобретение мной следующего имущества должника', style_left))
    story.append(Spacer(1, 30))
    story.append(Paragraph(f'{debtor_name}', style_left))
    story.append(Spacer(1, 7))
    story.append(Paragraph(f'Лот №{case_info.get("lastLegalCasenNumber", {}).get("value", "N/A")}: {property_desc}', style_left))
    story.append(Spacer(1, 7))
    story.append(Paragraph(f'Предлагаю цену: {bid_price} рублей 09 коп', style_left))
    story.append(Spacer(1, 60))
    story.append(Paragraph(f'Адрес получения корреспонденции по торгам: {APPLICANT_RES_ADDRESS}', style_left))
    story.append(Spacer(1, 7))
    story.append(Paragraph(f'Телефон для связи {APPLICANT_PHONE}', style_left))
    story.append(Spacer(1, 7))
    story.append(Paragraph(f'Электронная почта {APPLICANT_EMAIL}', style_left))
    story.append(Spacer(1, 7))
    story.append(Paragraph('Я подтверждаю, что обязуюсь соблюдать требования, указанные в сообщении о проведении торгов.', style_left))
    story.append(Spacer(1, 7))
    story.append(Paragraph('Сообщаю об отсутствии заинтересованности по отношению к должнику, кредиторам, финансовому управляющему, об отсутствии участия в капитале финансового управляющего, СРО Арбитражного управляющего.', style_left))
    story.append(Spacer(1, 20))
    
    if img:
        signature_data = [
            [
                Paragraph(f'Дата подачи заявки {day} {month} {year} года', style_left),
                img,
                Paragraph('ИП Э.В. Хисматова', style_left)
            ]
        ]
        signature_table = Table(signature_data, colWidths=[9*cm, 3*cm, 4*cm])
        signature_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),    
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),  
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),    
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), 
        ]))
        story.append(Spacer(1, 40))
        story.append(signature_table)
    else:
        story.append(Spacer(1, 40))
        story.append(Paragraph(f'Дата подачи заявки {day} {month} {year} года', style_left))
        story.append(Spacer(1, 20))
        story.append(Paragraph('ИП Э.В. Хисматова', style_left))

    doc.build(story)
    print(f"✓ PDF сгенерирован: {filename}")
    return filename

# Функция для отправки email с PDF
def send_email(subject, pdf_path, case_info=None):
    if not pdf_path or not os.path.exists(pdf_path):
        print("✗ PDF файл не найден, пропуск отправки email")
        return False
    if not EMAIL or not EMAIL_PASSWORD:
        print("✗ EMAIL или EMAIL_PASSWORD не установлены, пропуск отправки email")
        return False
    
    print(f"Отправка email с темой: {subject}, файл: {pdf_path}")

    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Subject'] = subject

    body = "Прошу вас не менять тему сообщения и отвечать на данное письмо, так как есть вероятность, что сообщения могут оказаться в спаме."
    msg.attach(MIMEText(body, 'plain'))

    with open(pdf_path, 'rb') as f:
        part = MIMEBase('application', 'pdf')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = "Заявка.pdf"
        part.add_header('Content-Disposition', 'attachment; filename*=UTF-8\'\'{}'.format(Header(filename, 'utf-8').encode()))
        msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_FROM, EMAIL_TO, text)
        server.quit()
        print("✓ Email отправлен через SMTP")
        return True
    except Exception as e:
        print(f"✗ Ошибка отправки email: {e}")
        return False

# HTTP обработчики для Render
async def handle_root(request):
    status = "running" if is_running else "stopped"
    return web.json_response({
        "status": status,
        "service": "Bankruptcy Monitor",
        "monitored_trustees": len(TRUSTEE_NAMES),
        "seen_cases": len(seen_cases),
        "pending_lots": len(pending_lots)
    })

async def handle_health(request):
    return web.Response(text="OK")

async def handle_status(request):
    return web.json_response({
        "is_running": is_running,
        "seen_cases_count": len(seen_cases),
        "pending_lots_count": len(pending_lots),
        "trustees": TRUSTEE_NAMES
    })

# Основная функция мониторинга
async def monitoring_loop():
    global seen_cases, pending_lots, is_running
    
    print("🔄 Запуск цикла мониторинга...")
    seen_cases = load_seen_cases()
    pending_lots = load_pending_lots()
    
    async with aiohttp.ClientSession() as session:
        iterations = 0
        while is_running:
            try:
                # API search for all trustees concurrently
                tasks = [search_cases_async(session, trustee) for trustee in TRUSTEE_NAMES]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for trustee, cases in zip(TRUSTEE_NAMES, results):
                    if isinstance(cases, Exception):
                        print(f"Ошибка для {trustee}: {cases}")
                        continue
                    
                    print(f"Найдено {len(cases)} дел для {trustee}")
                    
                    for case in cases:
                        guid = case['guid']['value']
                        if guid not in seen_cases:
                            seen_cases.append(guid)
                            
                            # Get details asynchronously
                            details = await get_case_details_async(session, guid)
                            if details and 'rez' in details:
                                case_info = details['rez'][0]
                                message = f"Новый лот от {trustee}: {case_info['lastLegalCasenNumber']['value']}"
                                print(f"Обработка нового лота: {message}")
                                
                                # Отправляем уведомление в Telegram
                                await send_to_telegram(message)
                                
                                # Генерируем PDF и отправляем по email
                                subject = f"Заявка на {case_info['lastLegalCasenNumber']['value']}"
                                pdf_path = generate_pdf(trustee, case_info)
                                send_email(subject, pdf_path, case_info)
                                
                                # Удаляем PDF после отправки
                                if os.path.exists(pdf_path):
                                    os.remove(pdf_path)
                                    print(f"✓ PDF удален: {pdf_path}")
                
                # Сохраняем состояние
                save_seen_cases(seen_cases)
                save_pending_lots(pending_lots)
                
                iterations += 1
                print(f"✅ Итерация {iterations} завершена. Ожидание 1 секунду...")
                
                # Ждем 1 секунду перед следующей проверкой
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"❌ Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(5)  # При ошибке ждем дольше
    
    print("🛑 Цикл мониторинга завершен")

# Функция для запуска HTTP сервера
async def run_http_server():
    app = web.Application()
    app.router.add_get('/', handle_root)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/status', handle_status)
    
    port = int(os.environ.get('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✓ HTTP сервер запущен на порту {port}")
    print(f"✓ Health check доступен по адресу: http://0.0.0.0:{port}/health")
    return runner

# Обработка сигналов завершения
def handle_shutdown(signum, frame):
    global is_running
    print(f"\n⚠️ Получен сигнал {signum}, завершаем работу...")
    is_running = False

# Главная функция
async def main():
    global is_running, monitoring_task
    
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    
    print("🚀 Запуск Bankruptcy Monitor на Render")
    print(f"📊 Отслеживаемые управляющие: {', '.join(TRUSTEE_NAMES)}")
    
    # Запускаем HTTP сервер
    http_runner = await run_http_server()
    
    # Запускаем мониторинг в фоне
    monitoring_task = asyncio.create_task(monitoring_loop())
    
    # Держим приложение запущенным
    try:
        while is_running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("⚠️ Задача отменена")
    finally:
        print("🛑 Остановка приложения...")
        is_running = False
        
        # Ждем завершения задачи мониторинга
        if monitoring_task and not monitoring_task.done():
            monitoring_task.cancel()
            try:
                await monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Останавливаем HTTP сервер
        await http_runner.cleanup()
        
        # Сохраняем состояние в последний раз
        save_seen_cases(seen_cases)
        save_pending_lots(pending_lots)
        print("✅ Состояние сохранено")

if __name__ == '__main__':
    test_mode = '--test' in sys.argv
    if test_mode:
        print("🧪 Запуск в тестовом режиме (только 2 итерации)")
        # Здесь можно добавить логику для тестового режима
        asyncio.run(main())
    else:
        asyncio.run(main())
