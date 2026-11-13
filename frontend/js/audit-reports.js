// 6. Audit & System Adjustments
const AUDIT_ACTION_MAP_UA = {
  // Auth
  'LOGIN': 'Вхід у систему',
  'LOGIN_FAIL': 'Невдала спроба входу',
  'LOGOUT': 'Вихід із системи',
  'AUTH_LOGIN_SUCCESS': 'Успішний вхід у систему',
  'AUTH_LOGIN_FAILED': 'Невдала спроба входу',
  'AUTH_LOGIN_LOCKED': 'Тимчасове блокування входу',
  'AUTH_LOGIN_BLOCKED': 'Блокування входу',
  'AUTH_LOGOUT': 'Вихід із системи',
  'USER_LOGIN': 'Вхід у систему',
  'USER_LOGOUT': 'Вихід із системи',

  // Generator
  'GENERATOR_START': 'Запуск генератора',
  'GENERATOR_STOP': 'Зупинка генератора',
  'GENERATOR_CREATE': 'Створення генератора',
  'GENERATOR_CREATED': 'Створення генератора',
  'GENERATOR_UPDATED': 'Оновлення параметрів генератора',
  'GENERATOR_DELETE': 'Видалення генератора',
  'GENERATOR_DELETED': 'Видалення генератора',
  'GENERATOR_ARCHIVED': 'Архівація генератора',
  'GENERATOR_RESTORED': 'Відновлення генератора з архіву',
  'GENERATOR_FACILITY_TRANSFERRED': 'Переміщення генератора між об\'єктами',
  'GENERATOR_FORCE_START_MAINTENANCE': 'Примусовий запуск при простроченому ТО',
  'GENERATOR_FUEL_RECONCILED': 'Звірка залишку пального в баку',
  'GENERATOR_SAFETY_STOP': 'Аварійна зупинка генератора (захист)',
  'GENERATOR_AUTO_STOP': 'Автоматична зупинка генератора (розклад)',
  'FUEL_STOCK_ARCHIVED': 'Архівація складу ГСМ',
  'BACKUP_CREATE': 'Створення резервної копії БД',
  'BACKUP_CREATED': 'Створення резервної копії БД',
  'BACKUP_RESTORE': 'Відновлення БД з резервної копії',
  'BACKUP_RESTORED': 'Відновлення БД з резервної копії',
  'BACKUP_DELETE': 'Видалення резервної копії БД',
  'BACKUP_DELETED': 'Видалення резервної копії БД',
  'BACKUP_DOWNLOAD': 'Завантаження архіву резервної копії',
  'BACKUP_SETTINGS_UPDATE': 'Оновлення налаштувань автобекапу',
  'NOTIFICATION_LOGS_CLEARED': 'Очищення журналу сповіщень',
  'WEEKLY_DIGEST_AUTO_SENT': 'Автоматичне відправлення щотижневого звіту',
  'GENERATOR_MANUAL_RUN_ADDED': 'Ручне внесення мотогодин',
  'GENERATOR_QUICK_CONFIG': 'Швидке налаштування генератора',
  'GENERATOR_WIZARD_CONFIGURED': 'Первинне налаштування генератора',
  'WIZARD_SETUP': 'Налаштування через майстер',

  // Fuel
  'FUEL_RECEIPT': 'Оприбуткування палива на склад',
  'FUEL_RECEIPT_ADDED': 'Оприбуткування палива на склад',
  'FUEL_DISPENSE': 'Заправка генератора',
  'FUEL_TRANSFER_TO_TANK': 'Заправка бака зі складу',
  'FUEL_TRANSFERRED': 'Заправка бака зі складу',
  'FUEL_STOCK_CREATED': 'Створення складу ГСМ',
  'FUEL_STOCK_UPDATED': 'Оновлення складу ГСМ',
  'FUEL_STOCK_DELETED': 'Видалення складу ГСМ',
  'FUEL_PRICES_REFRESHED': 'Оновлення цін палива (АЗК)',
  'CANISTER_POOL_CREATED': 'Створення пулу каністр',
  'CANISTER_POOL_UPDATED': 'Оновлення пулу каністр',
  'CANISTER_POOL_DELETED': 'Видалення пулу каністр',
  'CANISTER_DISPATCHED': 'Відправка каністр на заправку',
  'CANISTER_RECEIVED': 'Прийом заправлених каністр',
  'CANISTER_RETURNED_EMPTY': 'Повернення порожніх каністр без заправки',
  'POOL_ADJUSTMENT': 'Системне коригування каністр',

  // Maintenance
  'MAINTENANCE_RECORD': 'Технічне обслуговування',
  'MAINTENANCE_RECORDED': 'Запис ТО',
  'MAINTENANCE_INTERMEDIATE': 'Проміжне ТО',
  'MAINTENANCE_SCHEDULED': 'Регламентне ТО',
  'MAINTENANCE_SCHEDULE_RECALCULATED': 'Перерахунок графіка ТО',
  'SCHEDULE_RECALCULATED': 'Перерахунок графіка ТО',

  // Faults
  'FAULT_CREATE': 'Реєстрація несправності',
  'FAULT_REPORTED': 'Повідомлення про несправність',
  'FAULT_UPDATE': 'Оновлення несправності',
  'FAULT_STATUS_UPDATED': 'Зміна статусу несправності',
  'FAULT_RESOLVED': 'Усунення несправності',

  // Adjustments & Settings
  'ADJUSTMENT': 'Коригування лічильників',
  'ADJUSTMENT_APPLIED': 'Системне коригування лічильників',
  'SYSTEM_ADJUSTMENT': 'Системне коригування лічильників',
  'NOTIFICATION_SETTINGS_UPDATED': 'Оновлення налаштувань сповіщень',
  'SETTINGS_UPDATE': 'Зміна налаштувань',
  'SYSTEM_SETTINGS_UPDATED': 'Оновлення налаштувань',
  'SYSTEM_SETTINGS_RESET': 'Скидання системних налаштувань',
  'SYSTEM_FACTORY_RESET': 'Скидання до заводських налаштувань',
  'SYSTEM_CLEAR_DATA': 'Очищення робочих даних',
  'SYSTEM_FACILITY_CLEAN': 'Очищення даних об\'єкта',
  'SYSTEM_REPORTS_CLEAN': 'Очищення звітів',
  'SYSTEM_RESET': 'Очищення / скидання даних',

  // Users
  'USER_CREATE': 'Створення користувача',
  'USER_CREATED': 'Створення користувача',
  'USER_UPDATE': 'Редагування користувача',
  'USER_UPDATED': 'Редагування користувача',
  'USER_DELETED': 'Видалення користувача',
  'USER_PASSWORD_RESET': 'Скидання пароля користувача',
  'USER_TOGGLE_ACTIVE': 'Зміна активності користувача',
  'USER_DEACTIVATED': 'Деактивація користувача',
  'USER_CHANGED_OWN_PASSWORD': 'Зміна власного пароля',
  'USER_PASSWORD_RESET_REQUESTED': 'Запит на скидання пароля',
  'USER_PASSWORD_RESET_COMPLETED': 'Завершення скидання пароля',
  'PROFILE_UPDATED': 'Оновлення профілю користувача',
  'AVATAR_UPDATED': 'Оновлення аватара профілю',
  'AVATAR_DELETED': 'Видалення аватара профілю',
  'USER_AVATAR_UPDATED': 'Оновлення аватара користувача',
  'USER_AVATAR_DELETED': 'Видалення аватара користувача',
  'SMTP_TEST_SENT': 'Тестове відправлення SMTP',
  'WEEKLY_DIGEST_EMAIL_SENT': 'Відправлення щотижневого звіту (Email)',
  'EMAIL_UNSUBSCRIBED': 'Відмова від email-сповіщень',
  'EMAIL_RESUBSCRIBED': 'Поновлення email-сповіщень',
  'FUEL_RECEIPT_UPDATED': 'Оновлення оприбуткування палива',
  'FUEL_RECEIPT_DELETED': 'Видалення оприбуткування палива',
  'FACILITY_TRANSFER': 'Переміщення між об\'єктами',

  // Measurement Mode
  'MEASUREMENT_STARTED': 'Запуск режиму вимірювання витрати палива',
  'MEASUREMENT_TANK_FULL': 'Підтвердження повного баку та завершення заміру',
  'MEASUREMENT_TANK_EMPTY': 'Завершення контрольного заміру баку',
  'MEASUREMENT_INVENTORY_SUBMITTED': 'Подання комісійної інвентаризації',
  'MEASUREMENT_STATEMENT_DOWNLOADED': 'Завантаження PDF-відомості інвентаризації',
  'MEASUREMENT_APPROVED': 'Погодження інвентаризації та оновлення норми витрати',
  'MEASUREMENT_CANCELLED': 'Аварійне скасування вимірювання',

  // Facility
  'FACILITY_CREATE': 'Створення об\'єкта',
  'FACILITY_CREATED': 'Створення об\'єкта',
  'FACILITY_UPDATED': 'Оновлення об\'єкта',
  'FACILITY_DELETED': 'Видалення об\'єкта',
  'FACILITY_SETTINGS_UPDATE': 'Оновлення налаштувань об\'єкта'
};

const AUDIT_ENTITY_MAP_UA = {
  'User': 'Користувач',
  'Facility': 'Об\'єкт',
  'Generator': 'Генератор',
  'FuelStock': 'Склад палива',
  'CanisterPool': 'Пул каністр',
  'FuelReceipt': 'Оприбуткування палива',
  'FuelTransaction': 'Заправка палива',
  'FuelTransfer': 'Заправка палива',
  'GeneratorRun': 'Робота генератора',
  'MaintenanceRecord': 'Запис ТО',
  'MaintenanceSchedule': 'Графік ТО',
  'FaultReport': 'Несправність',
  'Fault': 'Несправність',
  'SystemSettings': 'Системні налаштування',
  'SystemSetting': 'Системні налаштування',
  'SystemAdjustment': 'Коригування',
  'FuelMeasurement': 'Контрольний замір',
  'System': 'Система',
  'backup': 'Резервна копія',
  'Backup': 'Резервна копія',
  'system_settings': 'Системні налаштування',
  'NotificationLog': 'Сповіщення',
  'Report': 'Звіт',
  'Auth': 'Авторизація',
  'Profile': 'Профіль'
};

const ADJUSTMENT_FIELD_MAP_UA = {
  'current_operating_hours': 'Мотогодини',
  'fuel_tank_level_l': 'Рівень у баку (л)',
  'status': 'Статус генератора',
  'nominal_consumption_l_per_h': 'Нормативний розхід (л/год)',
  'current_balance_l': 'Залишок на складі (л)',
  'full_count': 'Повні каністри (шт.)',
  'empty_count': 'Порожні каністри (шт.)',
  'away_refill_count': 'Каністри на АЗС (шт.)',
  'reserve_liters': 'Резервна ємність (л)',
  'interval_hours': 'Інтервал ТО (год)',
  'next_due_hours': 'Наступне ТО (мотогодини)',
  'last_performed_hours': 'Останнє ТО (мотогодини)',
  'name': 'Назва',
  'address': 'Адреса'
};

function formatAuditDetailsUa(detailsRaw, action) {
  if (!detailsRaw) return '-';
  let details = detailsRaw;
  if (typeof detailsRaw === 'string') {
    try {
      details = JSON.parse(detailsRaw);
    } catch (_) {
      return detailsRaw;
    }
  }
  if (!details || typeof details !== 'object') return String(details);

  // 1. Зупинка генератора
  if (details.duration_seconds !== undefined || details.calculated_consumption_l !== undefined) {
    const parts = [];
    if (details.duration_formatted) parts.push(`Час: ${details.duration_formatted}`);
    if (details.calculated_consumption_l !== undefined) parts.push(`Витрата: ${formatLiters(details.calculated_consumption_l)}`);
    if (details.end_fuel_level_l !== undefined) parts.push(`Залишок: ${formatLiters(details.end_fuel_level_l)}`);
    if (details.end_hours !== undefined) parts.push(`Мотогодини: ${formatHoursCounter(details.end_hours)}`);
    return parts.join(' | ') || JSON.stringify(details);
  }

  // 2. Запуск генератора
  if (details.start_hours !== undefined && details.start_fuel !== undefined) {
    return `Початкові мотогодини: ${formatHoursCounter(details.start_hours)} | Паливо в баку: ${formatLiters(details.start_fuel)}`;
  }

  // 3. Системне коригування
  if (details.field) {
    const fieldMap = {
      ...ADJUSTMENT_FIELD_MAP_UA,
      stock_balance_l: 'Залишок на складі'
    };
    const fName = fieldMap[details.field] || details.field;
    const fmtAdjVal = (v) => {
      if (v === undefined || v === null) return '-';
      if (typeof v === 'number') return Number(v.toFixed(2)).toString().replace('.', ',');
      return v;
    };
    let res = `Коригування '${fName}': ${fmtAdjVal(details.old_value)} ➔ ${fmtAdjVal(details.new_value)}`;
    if (details.reason) res += ` (${details.reason})`;
    return res;
  }

  // 4. Оприбуткування палива
  if (details.receipt_id !== undefined && details.cost_total !== undefined) {
    const stName = details.stock_name ? ` (${details.stock_name})` : '';
    const lit = details.liters !== undefined ? formatLiters(details.liters) : '-';
    const cst = details.cost_total !== undefined ? formatMoney(details.cost_total) : '-';
    return `Оприбутковано ${lit} на суму ${cst}${stName}`;
  }

  // 5. Заправка в бак
  if (details.liters !== undefined && (details.stock_before !== undefined || details.tank_before !== undefined)) {
    return `Заправлено в бак: ${formatLiters(details.liters)}`;
  }

  // 6. Користувачі
  if (details.login && (details.roles || action === 'USER_CREATED' || action === 'USER_DELETED' || action === 'USER_UPDATED')) {
    const roleMap = { superadmin: 'Суперадміністратор', admin: 'Адміністратор', operator: 'Оператор', viewer: 'Спостерігач' };
    const rolesUa = Array.isArray(details.roles) ? details.roles.map(r => roleMap[r] || r).join(', ') : '';
    const extra = [];
    if (details.full_name) extra.push(details.full_name);
    if (details.email) extra.push(details.email);
    if (details.is_active === false) extra.push('деактивовано');
    const extraStr = extra.length ? `, ${extra.join(', ')}` : '';
    return `Користувач: ${details.login}${extraStr}${rolesUa ? ` (Роль: ${rolesUa})` : ''}`;
  }

  // 6.1 Зміни параметрів генератора або об'єкта (Diff changes)
  if (details.changes && typeof details.changes === 'object') {
    const fieldMap = {
      name: 'Назва',
      model: 'Модель',
      manufacturer: 'Виробник',
      serial_number: 'Серійний номер',
      nominal_consumption_l_per_h: 'Нормативний розхід',
      tank_capacity_l: 'Місткість бака',
      fuel_type: 'Тип палива',
      rated_power_kw: 'Потужність',
      address: 'Адреса',
      default_fuel_provider: 'Мережа АЗК',
      current_operating_hours: 'Мотогодини',
      fuel_tank_level_l: 'Паливо в баку',
      status: 'Статус',
      is_configured: 'Налаштовано',
      timezone: 'Часовий пояс',
      work_schedule_start: 'Початок зміни',
      work_schedule_end: 'Кінець зміни'
    };
    const cParts = [];
    for (const [fKey, diff] of Object.entries(details.changes)) {
      const fUa = fieldMap[fKey] || fKey;
      if (diff && typeof diff === 'object' && ('old' in diff || 'new' in diff)) {
        cParts.push(`${fUa}: '${diff.old ?? '-'}' ➔ '${diff.new ?? '-'}'`);
      } else {
        cParts.push(`${fUa}: ${diff}`);
      }
    }
    if (cParts.length > 0) {
      const entityLabel = (action && action.includes('GENERATOR')) ? 'генератора' : ((action && action.includes('FACILITY')) ? "об'єкта" : '');
      const prefix = entityLabel ? `Змінено параметри ${entityLabel}: ` : 'Змінено параметри: ';
      return prefix + cParts.join('; ');
    }
  }

  // 6.2 Оновлення системних налаштувань (System settings updates)
  if (details.updates && typeof details.updates === 'object') {
    const settingMap = {
      organization_name: 'Організація',
      work_schedule_start: 'Початок зміни',
      work_schedule_end: 'Кінець зміни',
      enforce_work_schedule: 'Контроль графіка',
      facility_timezone: 'Часовий пояс',
      default_maintenance_interval_hours: 'Інтервал ТО',
      fuel_price_a95: 'Ціна А-95',
      fuel_price_dp: 'Ціна ДП',
      fuel_price_a92: 'Ціна А-92',
      auto_fetch_fuel_prices: 'Автооновлення цін палива',
      fuel_default_provider: 'Мережа за замовчуванням',
      max_continuous_run_hours: 'Макс. безперервна робота (год)',
      auto_stop_on_schedule_end: 'Автостоп наприкінці зміни',
      notify_running_heartbeat: 'Нагадування про активну роботу',
      heartbeat_interval_hours: 'Інтервал нагадування (год)',
      email_weekly_report_enabled: 'Щотижневий email-звіт',
      email_weekly_recipients: 'Отримувачі email-звіту',
      email_weekly_send_day: 'День відправлення email-звіту',
      email_weekly_send_time: 'Час відправлення email-звіту',
      email_weekly_facility_id: "Об'єкт для email-звіту (ID)",
      email_weekly_generator_id: 'Генератор для email-звіту (ID)',
      email_notify_password_change: 'Email-сповіщення про зміну пароля',
      email_notify_safety_stop: 'Email-сповіщення про автостоп',
      email_notify_empty_tank: 'Email-сповіщення про порожній бак (0 л)',
      email_notify_low_fuel: 'Email-сповіщення про низький рівень палива',
      email_notify_outside_schedule: 'Email-сповіщення про роботу поза графіком',
      email_notify_critical_fault: 'Email-сповіщення про критичну несправність',
      email_notify_maintenance_due: 'Email-сповіщення про наближення ТО',
      notify_outside_schedule: 'Сповіщення про роботу поза графіком',
      email_notifications_enabled: 'Email-сповіщення',
      smtp_enabled: 'SMTP увімкнено',
      smtp_primary_host: 'Основний SMTP-сервер',
      smtp_primary_port: 'Порт основного SMTP',
      smtp_primary_user: 'Користувач основного SMTP',
      smtp_primary_ssl: 'SSL основного SMTP',
      smtp_primary_from: 'Відправник основного SMTP',
      smtp_fallback_enabled: 'Резервний SMTP',
      smtp_fallback_host: 'Резервний SMTP-сервер',
      smtp_fallback_port: 'Порт резервного SMTP',
      smtp_fallback_user: 'Користувач резервного SMTP',
      smtp_fallback_ssl: 'SSL резервного SMTP',
      smtp_fallback_from: 'Відправник резервного SMTP',
      default_facility_id: "Об'єкт за замовчуванням (ID)",
      default_generator_id: 'Генератор за замовчуванням (ID)',
      default_fuel_stock_id: 'Склад ГСМ за замовчуванням (ID)',
      apply_to_all_generators: 'Застосувати до всіх генераторів',
      login_max_attempts: 'Ліміт спроб входу',
      login_lockout_seconds: 'Час блокування (с)',
      fuel_receipt_max_liters_warning: 'Поріг літрів чека',
      fuel_receipt_min_price: 'Мін. ціна палива',
      fuel_receipt_max_price: 'Макс. ціна палива'
    };
    const uParts = [];
    for (const [k, v] of Object.entries(details.updates)) {
      if (k.toLowerCase().includes('password') || k.toLowerCase().includes('secret') || k.toLowerCase().includes('token') || v === '***REDACTED***' || v === '[REDACTED]') continue;
      const kUa = settingMap[k] || k;
      let vStr = v;
      if (typeof v === 'boolean') vStr = v ? 'увімкнено' : 'вимкнено';
      else if (typeof v === 'string') vStr = `'${v}'`;
      uParts.push(`${kUa}: ${vStr}`);
    }
    if (uParts.length > 0) {
      return 'Оновлено системні налаштування: ' + uParts.join('; ');
    }
  }

  // 6.3 Видалення об'єкта (Facility deletion)
  if (action === 'FACILITY_DELETED' || (details.cascade !== undefined && details.fuel_stocks_deleted)) {
    const facName = details.name || '';
    const extraInfo = [];
    const gens = Array.isArray(details.generators_deleted) ? details.generators_deleted : [];
    const stocks = Array.isArray(details.fuel_stocks_deleted) ? details.fuel_stocks_deleted : [];
    const unbound = details.users_unbound_count || 0;
    if (gens.length > 0) extraInfo.push(`генераторів: ${gens.length}`);
    if (stocks.length > 0) extraInfo.push(`складів ГСМ: ${stocks.length}`);
    if (unbound > 0) extraInfo.push(`відкріплено користувачів: ${unbound}`);
    const cascadeStr = extraInfo.length > 0 ? ` (каскадно видалено ${extraInfo.join(', ')})` : '';
    return `Видалено об'єкт '${facName}'${cascadeStr}`;
  }

  // 6.4 Створення або оновлення об'єкта
  if (action && (action.startsWith('FACILITY_CREATE') || action.startsWith('FACILITY_UPDATE')) && (details.name || details.address)) {
    const parts = [];
    if (details.name) parts.push(`Об'єкт: '${details.name}'`);
    if (details.address) parts.push(`Адреса: '${details.address}'`);
    if (details.default_fuel_provider) parts.push(`Мережа: ${details.default_fuel_provider.toUpperCase()}`);
    return parts.join(' | ') || details.name;
  }

  // 6.5 Резервні копії (Backups)
  if (details.message && (String(details.message).toLowerCase().includes('backup') || String(details.message).toLowerCase().includes('бекап') || (action && action.includes('BACKUP')))) {
    const msg = String(details.message).trim();
    const subInfo = [];
    if (details.records_count !== undefined) subInfo.push(`записів БД: ${details.records_count}`);
    if (details.files_count !== undefined) subInfo.push(`файлів: ${details.files_count}`);
    if (details.notes) subInfo.push(String(details.notes));
    if (subInfo.length > 0) {
      return `${msg} (${subInfo.join(', ')})`;
    }
    return msg;
  }

  // 7. Сповіщення
  if (details.updated_keys) {
    return 'Оновлено параметри та перемикачі сповіщень';
  }

  // 8. Перерахунок регламенту ТО
  if (details.next_due_hours !== undefined && details.interval_hours !== undefined) {
    return `Мотогодини: ${details.current_hours !== undefined ? details.current_hours : '-'} год | Наступне планове ТО: ${details.next_due_hours} год`;
  }

  // 9. Запис ТО
  if (details.work && details.type) {
    const mType = details.type === 'SCHEDULED' ? 'Регламентне ТО' : 'Проміжне ТО';
    return `${mType} | Роботи: ${details.work} | Вартість: ${details.cost || 0} грн`;
  }

  // 9.5 Оновлення або видалення складу ГСМ (old / new diff objects)
  if ((action === 'FUEL_STOCK_UPDATED' || action === 'FUEL_STOCK_DELETED' || action === 'FUEL_STOCK_CREATED') && (details.old || details.new || details.name)) {
    if (details.old && details.new && typeof details.old === 'object' && typeof details.new === 'object') {
      const fDiffs = [];
      if (details.old.name !== details.new.name) fDiffs.push(`Назва: '${details.old.name}' ➔ '${details.new.name}'`);
      if (details.old.fuel_type !== details.new.fuel_type) fDiffs.push(`Тип палива: '${details.old.fuel_type}' ➔ '${details.new.fuel_type}'`);
      if (fDiffs.length > 0) return fDiffs.join(' | ');
    }
    const parts = [];
    if (details.name) parts.push(`Склад: '${details.name}'`);
    if (details.fuel_type) parts.push(`Паливо: ${details.fuel_type}`);
    if (details.initial_balance_l !== undefined) parts.push(`Початковий залишок: ${formatLiters(details.initial_balance_l)}`);
    if (details.balance_transferred_l !== undefined) parts.push(`Перенесено залишок: ${formatLiters(details.balance_transferred_l)}`);
    if (parts.length > 0) return parts.join(' | ');
  }

  // 9.6 Тест SMTP / Email-звіт (nested result)
  if ((action === 'SMTP_TEST_SENT' || action === 'WEEKLY_DIGEST_EMAIL_SENT' || action === 'EMAIL_UNSUBSCRIBED' || action === 'EMAIL_RESUBSCRIBED') || (details.result && typeof details.result === 'object')) {
    const smtpProviderMap = { primary: 'Основний SMTP', fallback: 'Резервний SMTP', failover: 'Автоперемикання SMTP' };
    const statusMap = { ok: 'Успішно', error: 'Помилка', skipped: 'Пропущено' };
    const eParts = [];
    if (details.recipient) eParts.push(`Отримувач: ${details.recipient}`);
    if (Array.isArray(details.recipients) && details.recipients.length > 0) eParts.push(`Отримувачі: ${details.recipients.join(', ')}`);
    if (details.email) eParts.push(`Ел. пошта: ${details.email}`);
    if (details.enabled !== undefined) eParts.push(`Підписка: ${details.enabled ? 'Увімкнено' : 'Вимкнено'}`);
    if (details.provider) eParts.push(`Режим: ${smtpProviderMap[String(details.provider).toLowerCase()] || details.provider}`);
    const resObj = details.result && typeof details.result === 'object' ? details.result : null;
    if (resObj) {
      if (resObj.status) eParts.push(`Статус: ${statusMap[String(resObj.status).toLowerCase()] || resObj.status}`);
      if (resObj.host) eParts.push(`Сервер: ${resObj.host}${resObj.port ? `:${resObj.port}` : ''}`);
      if (resObj.message) eParts.push(String(resObj.message));
      if (resObj.warning) eParts.push(`Попередження: ${resObj.warning}`);
      if (resObj.duration_ms !== undefined) eParts.push(`Час: ${resObj.duration_ms} мс`);
    }
    if (eParts.length > 0) return eParts.join(' | ');
  }

  // 10. Загальний переклад
  const roleMap = { superadmin: 'Суперадміністратор', admin: 'Адміністратор', operator: 'Оператор', viewer: 'Спостерігач' };
  const keyTrans = {
    title: 'Назва', description: 'Опис', priority: 'Пріоритет', status: 'Статус', operating_hours: 'Мотогодини',
    old_status: 'Попередній статус', new_status: 'Новий статус', resolution_notes: 'Примітка щодо усунення',
    generator_status_after: 'Статус генератора', status_after: 'Статус генератора',
    liters: 'Літри', cost: 'Вартість', cost_total: 'Загальна сума', source: 'Джерело', updated_at: 'Оновлено',
    name: 'Назва', fuel_type: 'Тип палива', reason: 'Причина', field: 'Поле', old_value: 'Було', new_value: 'Стало',
    address: 'Адреса', default_fuel_provider: 'Мережа АЗК', cascade: 'Каскадне видалення',
    generators_deleted: 'Видалені генератори', fuel_stocks_deleted: 'Видалені склади ГСМ',
    users_unbound_count: 'Відкріплено користувачів', records_count: 'Кількість записів',
    files_count: 'Кількість файлів', notes: 'Примітки', message: 'Повідомлення',
    comment: 'Коментар', old_name: 'Попередня назва', new_name: 'Нова назва',
    balance_transferred_l: 'Перенесено залишок (л)', initial_balance_l: 'Початковий залишок (л)',
    stock_name: 'Склад', pool_name: 'Пул каністр', generator_name: 'Генератор', facility_name: "Об'єкт",
    target_facility_name: "Цільовий об'єкт", target_name: "Цільовий об'єкт",
    count: 'Кількість', filename: 'Файл', retry_after_sec: 'Блокування (с)', user_login: 'Логін користувача',
    login: 'Логін', full_name: "Ім'я", email: 'Ел. пошта', is_active: 'Активний', enabled: 'Увімкнено', roles: 'Ролі',
    recipients: 'Отримувачі', recipient: 'Отримувач', period: 'Період', date: 'Дата',
    canister_volume_l: "Об'єм каністри (л)", total_count: 'Всього каністр (шт.)',
    full_count: 'Повні каністри (шт.)', empty_count: 'Порожні каністри (шт.)',
    away_refill_count: 'На АЗС (шт.)', reserve_liters: 'Резерв каністр (л)',
    driver: 'Водій', driver_name: 'Водій', receipt_no: 'Номер чека', receipt_number: 'Номер чека',
    price_per_l: 'Ціна за літр (грн)', price_per_liter: 'Ціна за літр (грн)', price_source: 'Джерело ціни',
    fuel_provider: 'Мережа АЗК', is_override: 'Ручне введення',
    stock_before: 'Склад до (л)', stock_after: 'Склад після (л)',
    provider: 'Мережа АЗК', old: 'Було', new: 'Стало',
    source_wog: 'Джерело WOG', updated_at_wog: 'Оновлено WOG',
    source_okko: 'Джерело OKKO', updated_at_okko: 'Оновлено OKKO',
    wog_dp: 'WOG ДП (грн/л)', okko_dp: 'OKKO ДП (грн/л)',
    wog_a95: 'WOG А-95 (грн/л)', okko_a95: 'OKKO А-95 (грн/л)',
    wog_a92: 'WOG А-92 (грн/л)', okko_a92: 'OKKO А-92 (грн/л)',
    model: 'Модель', serial_number: 'Серійний номер',
    deleted_stock_name: 'Видалений склад', transferred_balance_l: 'Перенесено залишок (л)',
    target_stock_name: 'Цільовий склад', archived: 'Архівовано',
    initial_hours: 'Початкові мотогодини', initial_fuel_level: 'Початковий рівень палива (л)',
    tank_capacity_l: 'Місткість бака (л)', tank_capacity: 'Місткість бака (л)', maint_interval: 'Інтервал ТО (год)',
    avatar_path: 'Файл аватара', empty_after: 'Порожніх після дії', away_after: 'На АЗС після дії',
    full_after: 'Повних після дії', reserve_after_l: 'Резерв після дії (л)',
    start_operating_hours: 'Початкові мотогодини', start_tank_level_l: 'Початковий рівень у баку (л)',
    old_nominal_consumption_l_per_h: 'Попередня норма витрати (л/год)',
    new_nominal_consumption_l_per_h: 'Нова норма витрати (л/год)',
    calculated_consumption_l_per_h: 'Фактична витрата (л/год)',
    duration_hours: 'Тривалість (год)', fuel_used_l: 'Використано палива (л)',
    start_hours: 'Початкові мотогодини', end_hours: 'Кінцеві мотогодини',
    start_time: 'Час запуску', end_time: 'Час зупинки',
    actual_balance_l: 'Фактичний залишок (л)', expected_balance_l: 'Очікуваний залишок (л)',
    difference_l: 'Розбіжність (л)', added_liters: 'Додано (л)', tank_level_after_l: 'Рівень у баку після (л)',
    context: 'Контекст', force_start_reason: 'Причина примусового запуску',
    forced_with_maintenance: 'Запуск при простроченому ТО',
    generator_tank_fact_l: 'Факт у баку генератора (л)', stocks_fact_total_l: 'Факт на складах (л)',
    total_fuel_consumed_l: 'Всього витрачено палива (л)', total_hours_elapsed: 'Напрацьовано (год)',
    start_balance_l: 'Початковий залишок (л)', commission_count: 'Членів комісії',
    commission_members: 'Склад комісії', statement_number: 'Номер відомості',
    measured_liters_before_cancel: 'Заміряно до скасування (л)',
    receipts_count: 'Приходів палива (шт.)', transfers_count: 'Заправок (шт.)',
    history_preserved: 'Історію збережено', mode: 'Режим',
    generators_reset: 'Скинуто генераторів', deleted_count: 'Видалено записів',
    faults: 'Несправностей', runs: 'Запусків', transfers: 'Заправок',
    maintenance_records: 'Записів ТО', schedule: 'Графік ТО',
    reports_clean: 'Очищення звітів', settings_reset: 'Скидання налаштувань',
    updated_settings: 'Оновлено параметрів',
    safety_backup_file: 'Захисний бекап (файл)', restore_files: 'Відновлення файлів',
    media_files_restored: 'Відновлено медіафайлів', records_restored: 'Відновлено записів БД',
    tables_count: 'Таблиць у бекапі', detail: 'Деталі', error: 'Помилка', success: 'Успіх', https: 'HTTPS'
  };
  const valTrans = {
    STOPPED: 'Зупинено', RUNNING: 'В роботі', MAINTENANCE: 'На обслуговуванні',
    MAINTENANCE_REQUIRED: 'Потрібне ТО', FAULT: 'Несправність', FAULTY: 'Несправний',
    BLOCKED: 'Заблоковано', ARCHIVED: 'В архіві',
    NEW: 'Нова', ACCEPTED: 'Прийнято', OPEN: 'Відкрита', IN_PROGRESS: 'В роботі',
    PENDING: 'В очікуванні', RESOLVED: 'Усунено', CLOSED: 'Закрито',
    LOW: 'Низький', MEDIUM: 'Середній', HIGH: 'Високий', CRITICAL: 'Критичний',
    SCHEDULED: 'Регламентне ТО', INTERMEDIATE: 'Проміжне ТО',
    WOG: 'WOG', OKKO: 'OKKO', ALL: 'Усі', INTERNET: 'Інтернет', MANUAL: 'Вручну',
    PRIMARY: 'Основний', FALLBACK: 'Резервний', FAILOVER: 'Автоперемикання',
    OK: 'Успішно', ERROR: 'Помилка',
    OPERATIONAL: 'Операційні дані', FULL: 'Повне очищення', SOFT: "М'яке очищення",
    TRUE: 'Так', FALSE: 'Ні'
  };
  const reasonPhraseTrans = {
    'Too many failed login attempts': 'Забагато невдалих спроб входу',
    'Invalid login or password': 'Невірний логін або пароль',
    'User is inactive/blocked': 'Обліковий запис деактивовано / заблоковано',
    '[REDACTED]': '[Приховано]'
  };

  const skipIds = new Set([
    'facility_id', 'generator_id', 'run_id', 'stock_id', 'target_stock_id',
    'pool_id', 'measurement_id', 'user_id', 'receipt_id', 'related_receipt_id',
    'old_facility_id', 'new_facility_id', 'safety_backup_id'
  ]);
  const formatScalarVal = (v) => {
    if (typeof v === 'string') return reasonPhraseTrans[v] || valTrans[v.toUpperCase()] || v;
    if (typeof v === 'boolean') return v ? 'Так' : 'Ні';
    return v;
  };
  const parts = [];
  for (const [k, v] of Object.entries(details)) {
    if (skipIds.has(k)) continue;
    if (v === null || v === undefined || v === '') continue;
    const kUa = keyTrans[k] || k;
    let vUa = v;
    if (typeof v === 'string' || typeof v === 'boolean') {
      vUa = formatScalarVal(v);
    } else if (Array.isArray(v)) {
      vUa = v.length > 0 ? v.map(item => roleMap[item] || formatScalarVal(item)).join(', ') : '-';
    } else if (typeof v === 'object') {
      const subParts = Object.entries(v)
        .filter(([, sv]) => sv !== null && sv !== undefined && sv !== '')
        .map(([sk, sv]) => `${keyTrans[sk] || sk}: ${Array.isArray(sv) ? sv.join(', ') : formatScalarVal(sv)}`);
      vUa = subParts.join(', ') || '-';
    }
    parts.push(`${kUa}: ${vUa}`);
  }
  return parts.join(' | ') || JSON.stringify(details);
}

// ROLE_MAP_UA defined at the top

async function loadAuditData() {
  try {
    const qFac = currentFacilityId ? `&facility_id=${encodeURIComponent(currentFacilityId)}` : '';
    const [logs, adjustments] = await Promise.all([
      api('/audit?limit=200'),
      api(`/adjustments?limit=200${qFac}`)
    ]);
    window.renderPaginatedTable('auditTable', logs, (l) => {
      const actionUa = AUDIT_ACTION_MAP_UA[l.action] || l.action;
      const entityUa = AUDIT_ENTITY_MAP_UA[l.entity_type] || l.entity_type;
      const detailsUa = formatAuditDetailsUa(l.details_json, l.action);
      return `
        <tr>
          <td>${formatDateTime(l.created_at)}</td>
          <td>${escapeHtml(l.user_name || 'Система')}</td>
          <td><b>${escapeHtml(actionUa)}</b></td>
          <td>${escapeHtml(entityUa)} #${escapeHtml(l.entity_id || '')}</td>
          <td style="font-size:0.82rem; line-height:1.4;">${escapeHtml(detailsUa)}</td>
          <td>${escapeHtml(l.ip_address || '-')}</td>
        </tr>
      `;
    }, 6, 'Аудит порожній', 10, true);

    window.renderPaginatedTable('adjustmentsTable', adjustments, (a) => {
      const entityUa = AUDIT_ENTITY_MAP_UA[a.entity_type] || a.entity_type;
      const fieldUa = ADJUSTMENT_FIELD_MAP_UA[a.field_name] || a.field_name;
      const facName = a.facility_name || (a.facility_id ? `Об'єкт #${a.facility_id}` : 'Базовий об\'єкт');
      const targetName = a.target_name || `${entityUa} #${a.entity_id}`;
      return `
        <tr>
          <td>${formatDateTime(a.created_at)}</td>
          <td>${escapeHtml(a.user_name || '-')}</td>
          <td><span class="badge" style="background: rgba(14, 165, 233, 0.15); color: #38bdf8;">${escapeHtml(facName)}</span></td>
          <td><b>${escapeHtml(targetName)}</b></td>
          <td>${escapeHtml(entityUa)}</td>
          <td>${escapeHtml(fieldUa)}</td>
          <td><s style="color:#ef4444;">${escapeHtml(a.old_value)}</s></td>
          <td><b style="color:#22c55e;">${escapeHtml(a.new_value)}</b></td>
          <td>${escapeHtml(a.reason)}</td>
        </tr>
      `;
    }, 9, 'Коригувань не виконувалось', 10, true);
  } catch (_) {}
}

window.openAuditExportModal = async function () {
  if (!isSuperAdmin()) {
    showToast('Експорт аудиту в Excel доступний виключно Головному Суперадміністратору 🔒', 'warning');
    return;
  }
  await window.openModal('modalExportAudit', { skipPostOpen: true });
  try {
    setAuditExportPeriod('month');
  } catch (err) {
    console.warn('Failed to set default audit export period:', err);
  }
};

window.setAuditExportPeriod = function (period) {
  const startInput = document.getElementById('auditExportStartDate');
  const endInput = document.getElementById('auditExportEndDate');
  if (!startInput || !endInput) return;

  const now = new Date();
  const toDateVal = (d) => {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  const todayStr = toDateVal(now);
  endInput.value = todayStr;

  if (period === 'today') {
    startInput.value = todayStr;
  } else if (period === 'week') {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    startInput.value = toDateVal(d);
  } else if (period === 'month') {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    startInput.value = toDateVal(d);
  } else if (period === 'all') {
    startInput.value = '';
    endInput.value = '';
  }
};

window.handleExportAuditExcel = async function (e) {
  if (e && e.preventDefault) e.preventDefault();
  if (!isSuperAdmin()) {
    showToast('Експорт аудиту в Excel доступний виключно Головному Суперадміністратору', 'warning');
    return;
  }

  const startInput = document.getElementById('auditExportStartDate');
  const endInput = document.getElementById('auditExportEndDate');
  const startVal = startInput ? startInput.value : '';
  const endVal = endInput ? endInput.value : '';

  let url = '/api/v1/audit/export-excel';
  const params = [];
  if (startVal) params.push(`start_date=${encodeURIComponent(startVal)}`);
  if (endVal) params.push(`end_date=${encodeURIComponent(endVal)}`);
  if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
  if (params.length) url += `?${params.join('&')}`;

  const submitBtn = document.getElementById('btnSubmitAuditExport');
  const origText = submitBtn ? submitBtn.innerHTML : '';
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = '⏳ Формування...';
  }

  try {
    showToast('Формування аудиторського Excel звіту (.xlsx)...', 'info');
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers, credentials: 'same-origin' });
    if (!res.ok) {
      let errMsg = `Помилка сервера при створенні Excel аудиту (${res.status})`;
      try {
        const errJson = await res.json();
        errMsg = extractErrorMessage(errJson, errMsg);
      } catch (_) {}
      throw new Error(errMsg);
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    const dateStr = new Date().toISOString().slice(0, 10);
    a.download = `Audit_Report_${dateStr}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('Аудиторський звіт Excel (.xlsx) успішно згенеровано та завантажено!', 'success');
    closeModal('modalExportAudit');
  } catch (err) {
    showToast(err.message || 'Помилка завантаження аудиторського звіту Excel', 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = origText;
    }
  }
};

window.openAdjustmentModal = async function() {
  if (!isSuperAdmin()) {
    showToast('Системне коригування лічильників доступне виключно Головному Суперадміністратору', 'warning');
    return;
  }
  await window.openModal('modalAdjustment', { skipPostOpen: true });

  // 1. Immediately & synchronously populate facility dropdown from header selector if available
  const mainFacSel = document.getElementById('facilitySelect');
  const facSel = document.getElementById('adjFacility');
  if (facSel && mainFacSel && mainFacSel.options.length > 0) {
    facSel.innerHTML = mainFacSel.innerHTML;
    if (currentFacilityId && Array.from(facSel.options).some(o => o.value == currentFacilityId)) {
      facSel.value = currentFacilityId;
    }
  }

  // 2. Synchronously ensure fields dropdown has initial options for current entity
  const fieldSelect = document.getElementById('adjField');
  const entitySel = document.getElementById('adjEntity');
  const entity = entitySel ? entitySel.value : 'FuelStock';
  if (fieldSelect && (!fieldSelect.options || fieldSelect.options.length === 0)) {
    if (entity === 'FuelStock') {
      fieldSelect.innerHTML = `
        <option value="current_balance_l">Залишок на складі (л)</option>
        <option value="name">Назва складу</option>
      `;
    } else if (entity === 'CanisterPool') {
      fieldSelect.innerHTML = `
        <option value="full_count">Повні каністри (шт.)</option>
        <option value="empty_count">Порожні каністри (шт.)</option>
        <option value="away_refill_count">На заправці / АЗС (шт.)</option>
        <option value="reserve_liters">Залишок у резерві (л)</option>
      `;
    } else if (entity === 'Generator') {
      fieldSelect.innerHTML = `
        <option value="current_operating_hours">Мотогодини</option>
        <option value="fuel_tank_level_l">Рівень у баку (л)</option>
        <option value="status">Статус генератора</option>
        <option value="nominal_consumption_l_per_h">Нормативний розхід (л/год)</option>
      `;
    }
  }

  // 3. Asynchronously load fresh data
  await setupAdjustmentModal();
};

async function setupAdjustmentModal() {
  try {
    const facSel = document.getElementById('adjFacility');
    let facilities = null;
    try {
      facilities = typeof window.getFacilitiesCached === 'function' ? await window.getFacilitiesCached() : await api('/facilities');
    } catch (_) {}

    if (facSel && facilities && Array.isArray(facilities) && facilities.length > 0) {
      facSel.innerHTML = facilities.map((f) => `<option value="${Number(f.id)}">${escapeHtml(f.name)}</option>`).join('');
      if (currentFacilityId && facilities.some((f) => f.id === currentFacilityId)) {
        facSel.value = currentFacilityId;
      }
    } else if (facSel && facSel.options.length === 0) {
      const mainFacSel = document.getElementById('facilitySelect');
      if (mainFacSel && mainFacSel.options.length > 0) {
        facSel.innerHTML = mainFacSel.innerHTML;
      } else {
        facSel.innerHTML = '<option value="1">Основний об\'єкт</option>';
      }
    }
  } catch (err) {
    console.warn('setupAdjustmentModal error:', err);
  } finally {
    await onAdjFacilityOrEntityChange();
  }
}
window.setupAdjustmentModal = setupAdjustmentModal;

window.onAdjFacilityOrEntityChange = async function() {
  const facSel = document.getElementById('adjFacility');
  const facilityId = (facSel && parseInt(facSel.value, 10)) || currentFacilityId || 1;
  const entity = document.getElementById('adjEntity').value;
  const targetSel = document.getElementById('adjTargetItem');
  const targetLabel = document.getElementById('adjTargetLabel');
  const fieldSelect = document.getElementById('adjField');

  if (entity === 'FuelStock') {
    if (targetLabel) targetLabel.innerText = 'Цільовий склад ГСМ';
    fieldSelect.innerHTML = `
      <option value="current_balance_l">Залишок на складі (л)</option>
      <option value="name">Назва складу</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження складів...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const stocks = await api(`/fuel/stocks${q}`);
      if (stocks && stocks.length > 0) {
        targetSel.innerHTML = stocks.map((s) => `
          <option value="${s.id}" data-type="FuelStock" data-balance="${s.current_balance_l}" data-name="${escapeHtml(s.name)}">
            ${escapeHtml(s.name)} (${escapeHtml(s.fuel_type)}) — залишок: ${s.current_balance_l} л
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає складів на цьому об'єкті</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="1" data-balance="0.0">Основний склад ГСМ (за замовчуванням)</option>`;
    }
  } else if (entity === 'CanisterPool') {
    if (targetLabel) targetLabel.innerText = 'Цільовий пул каністр';
    fieldSelect.innerHTML = `
      <option value="full_count">Повні каністри (шт.)</option>
      <option value="empty_count">Порожні каністри (шт.)</option>
      <option value="away_refill_count">На заправці / АЗС (шт.)</option>
      <option value="reserve_liters">Залишок у резерві (л)</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження пулів каністр...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const pools = await api(`/fuel/canisters${q}`);
      if (pools && pools.length > 0) {
        targetSel.innerHTML = pools.map((p) => `
          <option value="${p.id}" data-type="CanisterPool" data-full="${p.full_count}" data-empty="${p.empty_count}" data-away="${p.away_refill_count}" data-reserve="${p.reserve_liters}">
            ${escapeHtml(p.name)} (${escapeHtml(p.fuel_type)}, ${Number(p.canister_volume_l).toFixed(0)} л) — повних: ${p.full_count}, пустих: ${p.empty_count}, АЗС: ${p.away_refill_count}, рез: ${Number(p.reserve_liters).toFixed(1)} л
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає пулів каністр на цьому об'єкті</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="" disabled selected>Помилка завантаження пулів</option>`;
    }
  } else if (entity === 'Generator') {
    if (targetLabel) targetLabel.innerText = 'Цільовий генератор';
    fieldSelect.innerHTML = `
      <option value="current_operating_hours">Мотогодини</option>
      <option value="fuel_tank_level_l">Рівень у баку (л)</option>
      <option value="status">Статус генератора</option>
      <option value="nominal_consumption_l_per_h">Нормативний розхід (л/год)</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження генераторів...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const gens = await api(`/generator/list${q}`);
      if (gens && gens.length > 0) {
        targetSel.innerHTML = gens.map((g) => `
          <option value="${g.id}" data-type="Generator" data-hours="${g.current_operating_hours}" data-fuel="${g.fuel_tank_level_l}" data-status="${g.status}" data-consumption="${g.nominal_consumption_l_per_h}">
            ${escapeHtml(g.name)} (${escapeHtml(g.model || 'Генератор')})
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає генераторів на цьому об'єкті</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="" disabled selected>Помилка завантаження генераторів</option>`;
    }
  } else if (entity === 'MaintenanceSchedule') {
    if (targetLabel) targetLabel.innerText = 'Цільовий регламент ТО';
    fieldSelect.innerHTML = `
      <option value="interval_hours">Інтервал ТО (год)</option>
      <option value="next_due_hours">Наступне ТО (мотогодини)</option>
      <option value="last_performed_hours">Останнє ТО (мотогодини)</option>
    `;
    targetSel.innerHTML = '<option value="" disabled selected>Завантаження графіків ТО...</option>';
    try {
      const q = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
      const gens = await api(`/generator/list${q}`);
      const genIds = (gens || []).map(g => g.id);
      const scheds = await api('/maintenance/schedules');
      const filtered = (scheds || []).filter(s => genIds.length === 0 || genIds.includes(s.generator_id));
      if (filtered && filtered.length > 0) {
        targetSel.innerHTML = filtered.map((s) => `
          <option value="${s.id}" data-type="MaintenanceSchedule" data-interval="${s.interval_hours}" data-due="${s.next_due_hours}" data-performed="${s.last_performed_hours}">
            ${escapeHtml(s.title || 'Регламентне ТО')} (Генератор #${s.generator_id})
          </option>
        `).join('');
      } else {
        targetSel.innerHTML = `<option value="" disabled selected>Немає графіків ТО для об'єкта</option>`;
      }
    } catch (_) {
      targetSel.innerHTML = `<option value="1">Регламентне ТО (за замовчуванням)</option>`;
    }
  } else if (entity === 'Facility') {
    if (targetLabel) targetLabel.innerText = 'Цільовий об\'єкт';
    fieldSelect.innerHTML = `
      <option value="name">Назва об'єкта</option>
      <option value="address">Адреса об'єкта</option>
    `;
    const selOpt = facSel ? facSel.options[facSel.selectedIndex] : null;
    const facName = selOpt ? selOpt.text : `Об'єкт #${facilityId}`;
    targetSel.innerHTML = `<option value="${facilityId}" data-type="Facility" data-name="${escapeHtml(facName)}">${escapeHtml(facName)}</option>`;
  }

  onAdjTargetItemChange();
};

window.onAdjTargetItemChange = function() {
  onAdjFieldChange();
};

window.onAdjFieldChange = function() {
  const targetSel = document.getElementById('adjTargetItem');
  const field = document.getElementById('adjField').value;
  const hintEl = document.getElementById('adjCurrentValHint');
  const inputEl = document.getElementById('adjNewValue');
  if (!targetSel || !hintEl) return;

  const opt = targetSel.options[targetSel.selectedIndex];
  if (!opt || opt.disabled) {
    hintEl.innerText = '';
    return;
  }

  let val = '';
  if (field === 'current_balance_l') val = opt.getAttribute('data-balance') || '';
  else if (field === 'full_count') val = opt.getAttribute('data-full') || '';
  else if (field === 'empty_count') val = opt.getAttribute('data-empty') || '';
  else if (field === 'away_refill_count') val = opt.getAttribute('data-away') || '';
  else if (field === 'reserve_liters') val = opt.getAttribute('data-reserve') || '';
  else if (field === 'current_operating_hours') val = opt.getAttribute('data-hours') || '';
  else if (field === 'fuel_tank_level_l') val = opt.getAttribute('data-fuel') || '';
  else if (field === 'status') val = opt.getAttribute('data-status') || '';
  else if (field === 'nominal_consumption_l_per_h') val = opt.getAttribute('data-consumption') || '';
  else if (field === 'interval_hours') val = opt.getAttribute('data-interval') || '';
  else if (field === 'next_due_hours') val = opt.getAttribute('data-due') || '';
  else if (field === 'last_performed_hours') val = opt.getAttribute('data-performed') || '';
  else if (field === 'name') val = opt.getAttribute('data-name') || '';

  if (val !== '') {
    hintEl.innerText = `Поточне значення: ${val}`;
    if (inputEl && !inputEl.value) {
      inputEl.placeholder = `Поточне: ${val}`;
    }
  } else {
    hintEl.innerText = '';
    if (inputEl) inputEl.placeholder = 'Нове значення';
  }
};

window.updateAdjFields = function() {
  window.onAdjFacilityOrEntityChange();
};

document.addEventListener('submit', async (e) => {
  if (!e.target || e.target.id !== 'adjustmentForm') return;
  e.preventDefault();
  const facSel = document.getElementById('adjFacility');
  const facilityId = facSel ? parseInt(facSel.value, 10) : currentFacilityId;
  const entity = document.getElementById('adjEntity').value;
  const targetSel = document.getElementById('adjTargetItem');
  const targetId = targetSel ? parseInt(targetSel.value, 10) : null;
  const field = document.getElementById('adjField').value;
  const newVal = document.getElementById('adjNewValue').value.trim();
  const reason = document.getElementById('adjReason').value.trim();

  if (!targetId || isNaN(targetId)) {
    showToast('Будь ласка, оберіть цільовий склад або елемент для коригування', 'warning');
    return;
  }
  if (!newVal) {
    showToast('Введіть нове значення', 'warning');
    return;
  }
  if (reason.length < 5) {
    showToast('Обов\'язково вкажіть детальну причину коригування (не менше 5 символів)', 'warning');
    return;
  }

  try {
    await api('/adjustments', {
      method: 'POST',
      body: JSON.stringify({
        entity_type: entity,
        entity_id: targetId,
        facility_id: facilityId || null,
        field_name: field,
        new_value: newVal,
        reason: reason
      })
    });
    closeModal('modalAdjustment');
    showToast('Системне коригування успішно виконано та внесено в журнал аудиту!', 'success');
    loadAuditData();
    loadAllData();
    if (typeof loadFuelData === 'function') loadFuelData();
  } catch (_) {}
});

// 7. Reports
window.setReportPeriod = function(preset) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  let start = new Date(now);
  let end = new Date(now);

  if (preset === 'today') {
    // start is today
  } else if (preset === 'week') {
    start.setDate(now.getDate() - 7);
  } else if (preset === 'month') {
    start.setMonth(now.getMonth() - 1);
  } else if (preset === 'quarter') {
    start.setMonth(now.getMonth() - 3);
  } else if (preset === 'all') {
    start = new Date(2020, 0, 1);
  }

  // Highlight active preset button
  const presetButtons = document.querySelectorAll('#reportPresetGroup button');
  presetButtons.forEach(btn => {
    if (btn.getAttribute('data-preset') === preset) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  const startEl = document.getElementById('repStartDate');
  const endEl = document.getElementById('repEndDate');
  if (startEl) startEl.value = fmt(start);
  if (endEl) endEl.value = fmt(end);

  loadReport(true);
};

window.onReportCustomDateChange = function() {
  const presetButtons = document.querySelectorAll('#reportPresetGroup button');
  presetButtons.forEach(btn => btn.classList.remove('active'));
};

window.switchReportSubtab = function(tabKey) {
  const tabs = ['runs', 'transfers', 'receipts', 'maint', 'measurements'];
  const tabBtnMap = {
    runs: 'btnRepTabRuns',
    transfers: 'btnRepTabTransfers',
    receipts: 'btnRepTabReceipts',
    maint: 'btnRepTabMaint',
    measurements: 'btnRepTabMeasurements'
  };
  const paneMap = {
    runs: 'repPaneRuns',
    transfers: 'repPaneTransfers',
    receipts: 'repPaneReceipts',
    maint: 'repPaneMaint',
    measurements: 'repPaneMeasurements'
  };

  tabs.forEach(key => {
    const btn = document.getElementById(tabBtnMap[key]);
    const pane = document.getElementById(paneMap[key]);
    if (btn) {
      if (key === tabKey) btn.classList.add('active');
      else btn.classList.remove('active');
    }
    if (pane) {
      pane.style.display = (key === tabKey) ? 'block' : 'none';
    }
  });
};

async function loadReport(isUserTriggered = false) {
  const startInput = document.getElementById('repStartDate')?.value;
  const endInput = document.getElementById('repEndDate')?.value;
  const btn = document.getElementById('btnGenerateReport');
  const iconEl = document.getElementById('btnGenerateReportIcon');
  const textEl = document.getElementById('btnGenerateReportText');

  if (isUserTriggered && btn) {
    btn.disabled = true;
    if (iconEl) iconEl.textContent = '⏳';
    if (textEl) textEl.textContent = 'Формування...';
  }

  const params = [];
  if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
  if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
  if (startInput) params.push(`start_date=${encodeURIComponent(startInput)}`);
  if (endInput) params.push(`end_date=${encodeURIComponent(endInput)}`);
  const q = params.length ? '?' + params.join('&') : '';

  try {
    const r = await api(`/reports/summary${q}`);
    const startEl = document.getElementById('repStartDate');
    const endEl = document.getElementById('repEndDate');
    if (startEl && !startEl.value && r.start_date) startEl.value = String(r.start_date).slice(0, 10);
    if (endEl && !endEl.value && r.end_date) endEl.value = String(r.end_date).slice(0, 10);

    // 1. Update Status Banner
    const banner = document.getElementById('reportStatusBanner');
    const statusPeriod = document.getElementById('reportStatusPeriod');
    const statusTarget = document.getElementById('reportStatusTarget');
    const statusGenAt = document.getElementById('reportStatusGeneratedAt');
    if (banner && statusPeriod && statusTarget && statusGenAt) {
      let daysCount = '';
      if (r.start_date && r.end_date) {
        const d1 = new Date(r.start_date);
        const d2 = new Date(r.end_date);
        const diffDays = Math.round(Math.abs(d2 - d1) / (1000 * 60 * 60 * 24)) + 1;
        daysCount = ` (${diffDays} ${diffDays === 1 ? 'день' : (diffDays < 5 ? 'дні' : 'днів')})`;
      }
      const periodStart = r.start_date_human || formatDateOnly(r.start_date);
      const periodEnd = r.end_date_human || formatDateOnly(r.end_date);
      statusPeriod.textContent = `Період звітності: ${periodStart} — ${periodEnd}${daysCount}`;
      const facName = r.facility_name || (facilitySelect?.selectedOptions?.[0]?.text || 'Основний об\'єкт');
      const genName = r.generator_name || (generatorSelect?.selectedOptions?.[0]?.text || 'Генератор');
      statusTarget.textContent = `Об'єкт: ${facName} | Обладнання: ${genName}`;
      const nowStr = formatDateTime(new Date());
      statusGenAt.textContent = `Сформовано: ${nowStr}`;
      banner.style.display = 'flex';
    }

    // 2. Metrics Cards
    const container = document.getElementById('reportContainer');
    const totalCosts = (r.total_costs_uah !== undefined && r.total_costs_uah !== null)
      ? r.total_costs_uah
      : (Number(r.total_fuel_receipts_cost_uah || 0) + Number(r.total_maintenance_cost_uah || 0)).toFixed(2);

    const avgCons = (r.avg_consumption_l_per_hour !== undefined && r.avg_consumption_l_per_hour !== null)
      ? r.avg_consumption_l_per_hour
      : (r.total_operating_hours > 0 ? (r.total_calculated_consumption_l / r.total_operating_hours).toFixed(2) : 0);

    const avgRunDur = (r.avg_run_duration_hours !== undefined && r.avg_run_duration_hours !== null)
      ? r.avg_run_duration_hours
      : (r.total_runs_count > 0 ? (r.total_operating_hours / r.total_runs_count) : 0);

    const totalOperatingHoursDisplay = r.total_operating_hours_human || formatHoursToHuman(r.total_operating_hours);
    const avgRunDurationDisplay = r.avg_run_duration_human || formatHoursToHuman(avgRunDur);

    container.innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Відпрацьовано мотогодин</div>
        <div class="metric-value">${escapeHtml(totalOperatingHoursDisplay)}</div>
        <div class="metric-sub">${escapeHtml(r.total_runs_count)} пусків (сер. ${escapeHtml(avgRunDurationDisplay)})</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Розрахунковий розхід палива</div>
        <div class="metric-value">${escapeHtml(formatLiters(r.total_calculated_consumption_l))}</div>
        <div class="metric-sub">Сер. розхід: ${escapeHtml(formatLiters(avgCons))}/год</div>
      </div>
      <div class="metric-card" style="border-color: rgba(34, 197, 94, 0.4);">
        <div class="metric-label">Загальні витрати за період</div>
        <div class="metric-value" style="color: #4ade80;">${escapeHtml(formatMoney(totalCosts))}</div>
        <div class="metric-sub">Паливо: ${escapeHtml(formatMoney(r.total_fuel_receipts_cost_uah))} | ТО: ${escapeHtml(formatMoney(r.total_maintenance_cost_uah))}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Оприбутковано на склад</div>
        <div class="metric-value">${escapeHtml(formatLiters(r.total_fuel_received_l))}</div>
        <div class="metric-sub">${escapeHtml(formatMoney(r.total_fuel_receipts_cost_uah))} (${escapeHtml(formatPricePerLiter(r.avg_fuel_price_per_liter))})</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Заправлено в бак</div>
        <div class="metric-value">${escapeHtml(formatLiters(r.total_fuel_transferred_to_tank_l))}</div>
        <div class="metric-sub">Залишок у баку: ${escapeHtml(formatLiters(r.current_tank_level_l))}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Виконано ТО</div>
        <div class="metric-value">${escapeHtml(r.total_maintenance_count)}</div>
        <div class="metric-sub">Регламентних: ${escapeHtml(r.scheduled_maintenance_count)} | Проміжних: ${escapeHtml(r.intermediate_maintenance_count)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Витрати на сервіс / ТО</div>
        <div class="metric-value">${escapeHtml(formatMoney(r.total_maintenance_cost_uah))}</div>
        <div class="metric-sub">${escapeHtml(r.total_maintenance_count)} операцій обслуговування</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Несправності / Інциденти</div>
        <div class="metric-value">${escapeHtml(r.total_faults_count)}</div>
        <div class="metric-sub">Усунено: ${escapeHtml(r.resolved_faults_count)} | Відкрито: ${escapeHtml(r.open_faults_count)}</div>
      </div>
    `;

    // 3. Detailed Logs & Subtabs
    const detailsSection = document.getElementById('reportDetailsSection');
    if (detailsSection) {
      detailsSection.style.display = 'block';

      const runs = r.runs || [];
      const transfers = r.fuel_transfers || [];
      const receipts = r.fuel_receipts || [];
      const maint = r.maintenance_records || [];
      const measurements = r.measurements || [];

      // Badges
      const bRuns = document.getElementById('repBadgeRuns');
      const bTr = document.getElementById('repBadgeTransfers');
      const bRec = document.getElementById('repBadgeReceipts');
      const bMaint = document.getElementById('repBadgeMaint');
      const bMeas = document.getElementById('repBadgeMeasurements');
      if (bRuns) bRuns.textContent = runs.length;
      if (bTr) bTr.textContent = transfers.length;
      if (bRec) bRec.textContent = receipts.length;
      if (bMaint) bMaint.textContent = maint.length;
      if (bMeas) bMeas.textContent = measurements.length;

      // Table 1: Runs (Paginated: 10 per page)
      window.renderPaginatedTable('repRunsTable', runs, row => `
        <tr>
          <td><b>${escapeHtml(row.start_time)}</b></td>
          <td>${escapeHtml(row.end_time || 'В роботі')}</td>
          <td><b style="color: #38bdf8; font-family: monospace;">${escapeHtml(row.duration_formatted || formatHoursToHms(row.duration_hours))}</b></td>
          <td>${formatHoursCounter(row.start_hours)} ➔ ${row.end_hours !== null && row.end_hours !== undefined ? formatHoursCounter(row.end_hours) : '-'}</td>
          <td style="color:#38bdf8; font-weight:600;">${formatLiters(row.calculated_consumption_l)}</td>
          <td>${escapeHtml(row.operator_name || '-')}</td>
        </tr>
      `, 6, 'Немає зафіксованих пусків за обраний період', 10);

      // Table 2: Fuel Transfers (Paginated: 10 per page)
      window.renderPaginatedTable('repTransfersTable', transfers, row => `
        <tr>
          <td><b>${escapeHtml(row.created_at)}</b></td>
          <td style="color:#4ade80; font-weight:700;">${formatLiters(row.liters)}</td>
          <td>${escapeHtml(row.stock_name || 'Склад ГСМ')}</td>
          <td>${escapeHtml(row.generator_name || 'Генератор')}</td>
          <td>${escapeHtml(row.operator_name || '-')}</td>
        </tr>
      `, 5, 'Немає заправок бака за обраний період', 10);

      // Table 3: Fuel Receipts (Paginated: 10 per page)
      window.renderPaginatedTable('repReceiptsTable', receipts, row => `
        <tr>
          <td><b>${escapeHtml(row.created_at)}</b></td>
          <td style="color:#4ade80; font-weight:700;">${formatLiters(row.liters)}</td>
          <td>${formatPricePerLiter(row.price_per_liter)}</td>
          <td style="font-weight:600;">${formatMoney(row.cost_total)}</td>
          <td>${escapeHtml(row.supplier || '-')}</td>
          <td>${escapeHtml(row.stock_name || 'Склад ГСМ')}</td>
          <td>${escapeHtml(row.operator_name || '-')}</td>
        </tr>
      `, 7, 'Немає надходжень на склад за обраний період', 10);

      // Table 4: Maintenance (Paginated: 10 per page)
      window.renderPaginatedTable('repMaintTable', maint, row => `
        <tr>
          <td><b>${escapeHtml(row.created_at)}</b></td>
          <td><span class="badge" style="background: rgba(6,182,212,0.15); color: var(--accent-cyan);">${escapeHtml(row.maintenance_type)}</span></td>
          <td>${formatHoursCounter(row.operating_hours)}</td>
          <td>${escapeHtml(row.work_description || '-')}</td>
          <td style="font-weight:600;">${formatMoney(row.cost)}</td>
          <td>${escapeHtml(row.technician || '-')}</td>
          <td>${escapeHtml(row.operator_name || '-')}</td>
        </tr>
      `, 7, 'Немає записів обслуговування за обраний період', 10);

      // Table 5: Measurements & Inventory (Paginated: 10 per page)
      window.renderPaginatedTable('repMeasurementsTable', measurements, row => {
        const pdfLink = isSuperAdmin()
          ? ` <button type="button" class="btn-oq-chip btn-oq-chip-info" style="margin-left:0.35rem;" onclick="downloadMeasurementPdf(${Number(row.id)})">📥 PDF</button>`
          : '';
        return `
          <tr>
            <td><b>${escapeHtml(row.approved_at)}</b></td>
            <td><b>${escapeHtml(row.statement_number)}</b>${pdfLink}</td>
            <td>${escapeHtml(row.generator_name || '-')}</td>
            <td><b>${Number(row.total_fuel_consumed_l || 0).toFixed(1)} л</b> / ${Number(row.total_hours_elapsed || 0).toFixed(2)} год</td>
            <td>${Number(row.old_consumption_l_per_h || 0).toFixed(2)} ➔ <b style="color:#4ade80;">${Number(row.new_consumption_l_per_h || 0).toFixed(3)}</b></td>
            <td style="font-size:0.8rem;">${escapeHtml(row.commission_summary || '-')}</td>
            <td>${escapeHtml(row.approved_by_name || '-')}</td>
          </tr>`;
      }, 7, 'Немає проведених замірів та інвентаризацій за обраний період', 10);
    }

    if (isUserTriggered) {
      const periodStart = r.start_date_human || formatDateOnly(r.start_date);
      const periodEnd = r.end_date_human || formatDateOnly(r.end_date);
      showToast(`Звіт за період ${periodStart} — ${periodEnd} успішно сформовано!`, 'success');
    }
  } catch (err) {
    const container = document.getElementById('reportContainer');
    if (container) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; background: rgba(239, 68, 68, 0.12); border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 0.75rem; padding: 1.5rem; text-align: center; color: #f87171;">
          <div style="font-size: 1.15rem; font-weight: 700; margin-bottom: 0.35rem;">⚠️ Не вдалося завантажити показники звіту</div>
          <div style="font-size: 0.95rem;">${escapeHtml(err.message || 'Помилка отримання зведених даних')}</div>
        </div>
      `;
    }
    if (isUserTriggered) {
      showToast(`Помилка формування звіту: ${err.message || 'Невідома помилка'}`, 'error');
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      if (iconEl) iconEl.textContent = '🔄';
      if (textEl) textEl.textContent = 'Сформувати звіт';
    }
  }
}

window.downloadReportCSV = function () {
  showToast('Експорт у форматі CSV вимкнено. Звіти формуються виключно у форматі Excel (.xlsx)', 'info');
};

window.downloadReportExcel = async function () {
  const startInput = document.getElementById('repStartDate').value;
  const endInput = document.getElementById('repEndDate').value;
  let url = '/api/v1/reports/export-excel';
  const params = [];
  if (currentGeneratorId) params.push(`generator_id=${encodeURIComponent(currentGeneratorId)}`);
  if (currentFacilityId) params.push(`facility_id=${encodeURIComponent(currentFacilityId)}`);
  if (startInput) params.push(`start_date=${encodeURIComponent(startInput)}`);
  if (endInput) params.push(`end_date=${encodeURIComponent(endInput)}`);
  if (params.length) url += `?${params.join('&')}`;

  try {
    showToast('Формування динамічного Excel звіту (.xlsx)...', 'info');
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(url, { headers, credentials: 'same-origin' });
    if (!res.ok) {
      let errMsg = `Помилка сервера при створенні Excel (${res.status})`;
      try {
        const errJson = await res.json();
        errMsg = extractErrorMessage(errJson, errMsg);
      } catch (_) {}
      throw new Error(errMsg);
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = window.URL.createObjectURL(blob);
    const dateStr = new Date().toISOString().slice(0, 10);
    a.download = `ServiceDesk_Report_${dateStr}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('Excel звіт (.xlsx) успішно згенеровано та завантажено!', 'success');
  } catch (err) {
    showToast(err.message || 'Помилка завантаження Excel звіту', 'error');
  }
};

