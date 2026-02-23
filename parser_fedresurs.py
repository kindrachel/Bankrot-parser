"""
Парсер банкротных торгов с bankrot.fedresurs.ru
Использует Selenium для получения данных из SPA приложения
"""

import json
import time
import re
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


TRUSTEE_NAMES = [
    'Мурдашева Алсу Ишбулатновна',
    'Калашникова Наталья Александровна',
    'Закиров Тимур Назифович',
    'Фамиев Ильнур Илдусович',
    'Галеева Алина Рифмеровна',
    'Тихонова Кристина Александровна'
]

# Дата, не ранее которой искать торги (22.02.2026)
MIN_DATE = datetime(2026, 2, 22)


def create_driver():
    """Создание драйвера Chrome с настройками для headless режима"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Без GUI
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    # Отключаем автоматизацию
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        return driver
    except Exception as e:
        print(f"Ошибка создания драйвера: {e}")
        return None


def parse_date(date_str):
    """Парсинг даты из строки"""
    try:
        # Форматы дат: "22.02.2026", "22 февраля 2026", etc.
        patterns = [
            r'(\d{2})\.(\d{2})\.(\d{4})',
            r'(\d{2})\s+(\w+)\s+(\d{4})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                if '.' in date_str:
                    day, month, year = match.groups()
                    return datetime(int(year), int(month), int(day))
                else:
                    # Русские месяцы
                    months = {
                        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
                        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
                        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
                    }
                    day, month_str, year = match.groups()
                    month = months.get(month_str.lower(), 1)
                    return datetime(int(year), month, int(day))
    except Exception as e:
        print(f"Ошибка парсинга даты '{date_str}': {e}")
    
    return None


def search_trades_by_trustee(driver, trustee_name):
    """Поиск торгов по имени управляющего"""
    trades = []
    
    try:
        # Открываем страницу торгов
        url = 'https://bankrot.fedresurs.ru/trades'
        driver.get(url)
        
        # Ждем загрузки страницы
        wait = WebDriverWait(driver, 30)
        
        # Ищем поле поиска (может быть разное в зависимости от версии сайта)
        try:
            # Пробуем найти поле поиска по управляющему
            search_input = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="управляющий"], input[placeholder*="Управляющий"], input[name*="trustee"], input[name*="arbitr"]'))
            )
            search_input.clear()
            search_input.send_keys(trustee_name)
            
            # Ищем кнопку поиска
            search_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"], button.search-btn, .search-button')
            search_button.click()
            
        except Exception as e:
            print(f"Не удалось найти поле поиска для {trustee_name}: {e}")
            # Пробуем альтернативный способ - через URL параметры
            search_url = f'https://bankrot.fedresurs.ru/trades?search={trustee_name.replace(" ", "%20")}'
            driver.get(search_url)
        
        # Ждем загрузки результатов
        time.sleep(5)
        
        # Ищем элементы с торгами
        trade_elements = driver.find_elements(By.CSS_SELECTOR, '.trade-item, .lot-item, [class*="trade"], [class*="lot"]')
        
        for element in trade_elements:
            try:
                # Извлекаем данные о торге
                trade_data = {
                    'trustee_name': trustee_name,
                    'debtor_name': '',
                    'lot_number': '',
                    'description': '',
                    'publish_date': '',
                    'guid': '',
                    'url': ''
                }
                
                # Пробуем найти различные поля
                try:
                    trade_data['debtor_name'] = element.find_element(By.CSS_SELECTOR, '.debtor-name, [class*="debtor"]').text
                except:
                    pass
                
                try:
                    trade_data['lot_number'] = element.find_element(By.CSS_SELECTOR, '.lot-number, [class*="lot"]').text
                except:
                    pass
                
                try:
                    trade_data['description'] = element.find_element(By.CSS_SELECTOR, '.description, [class*="desc"]').text
                except:
                    pass
                
                try:
                    date_element = element.find_element(By.CSS_SELECTOR, '.date, [class*="date"], [class*="publish"]')
                    trade_data['publish_date'] = date_element.text
                except:
                    pass
                
                try:
                    link = element.find_element(By.TAG_NAME, 'a')
                    trade_data['url'] = link.get_attribute('href')
                    # Извлекаем GUID из URL если есть
                    guid_match = re.search(r'guid=([a-f0-9-]+)', trade_data['url'])
                    if guid_match:
                        trade_data['guid'] = guid_match.group(1)
                except:
                    pass
                
                # Проверяем дату
                if trade_data['publish_date']:
                    trade_date = parse_date(trade_data['publish_date'])
                    if trade_date and trade_date >= MIN_DATE:
                        trades.append(trade_data)
                    elif not trade_date:
                        # Если не удалось распарсить дату, добавляем на всякий случай
                        trades.append(trade_data)
                else:
                    # Если нет даты, добавляем для проверки
                    trades.append(trade_data)
                    
            except Exception as e:
                print(f"Ошибка обработки элемента торга: {e}")
                continue
        
        print(f"Найдено {len(trades)} торгов для {trustee_name}")
        
    except Exception as e:
        print(f"Ошибка поиска для {trustee_name}: {e}")
    
    return trades


def get_all_trades():
    """Получение всех торгов для всех управляющих"""
    all_trades = []
    
    driver = create_driver()
    if not driver:
        print("Не удалось создать драйвер")
        return all_trades
    
    try:
        for trustee_name in TRUSTEE_NAMES:
            print(f"\nПоиск торгов для: {trustee_name}")
            trades = search_trades_by_trustee(driver, trustee_name)
            all_trades.extend(trades)
            time.sleep(2)  # Пауза между запросами
        
        # Удаляем дубликаты по GUID
        seen_guids = set()
        unique_trades = []
        for trade in all_trades:
            if trade['guid'] and trade['guid'] not in seen_guids:
                seen_guids.add(trade['guid'])
                unique_trades.append(trade)
            elif not trade['guid']:
                unique_trades.append(trade)
        
        print(f"\nВсего уникальных торгов: {len(unique_trades)}")
        return unique_trades
        
    except Exception as e:
        print(f"Ошибка: {e}")
        return all_trades
    finally:
        driver.quit()


def save_trades_to_json(trades, filename='trades_fedresurs.json'):
    """Сохранение торгов в JSON файл"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)
    print(f"Сохранено {len(trades)} торгов в {filename}")


if __name__ == '__main__':
    print("=== Парсер банкротных торгов с fedresurs.ru ===")
    print(f"Дата фильтра: не ранее {MIN_DATE.strftime('%d.%m.%Y')}")
    print(f"Управляющие: {len(TRUSTEE_NAMES)}")
    
    trades = get_all_trades()
    
    if trades:
        save_trades_to_json(trades)
        print("\nНайденные торги:")
        for i, trade in enumerate(trades[:5], 1):
            print(f"{i}. {trade.get('debtor_name', 'N/A')} - {trade.get('lot_number', 'N/A')}")
            print(f"   Дата: {trade.get('publish_date', 'N/A')}")
            print(f"   Управляющий: {trade.get('trustee_name', 'N/A')}")
            print()
    else:
        print("Торги не найдены")
