# Архітектурна специфікація: Облік каністр у пулах об'єктів та резервної ємності (Реалізовано — Етап 2)

**Статус:** ✅ Реалізовано у бекенді, Alembic (`011_canister_pools`), REST API та PWA-інтерфейсі  
**Пов'язані модулі:** [`canister.py`](../backend/app/models/canister.py), [`canister_service.py`](../backend/app/services/canister_service.py), [`fuel_service.py`](../backend/app/services/fuel_service.py), [`fuel.py`](../backend/app/api/v1/fuel.py), [`fuel.js`](../frontend/js/fuel.js)

---

## 1. Доменна модель та бізнес-логіка

На об'єктах відсутній стаціонарний резервуар — усе паливо складу (`FuelStock`) зберігається у **закріпленому за об'єктом пулі каністр** певного номіналу (наприклад, `5 × 20 л`, певний тип палива) разом з **резервною ємністю** для залишків.

### 1.1. Інваріанти пулу каністр (`CanisterPool`)
Облік ведеться у простих цілих штуках:
- `total_count` — закріплена за об'єктом кількість каністр (`total_count == full_count + empty_count + away_refill_count`);
- `full_count` — повні запечатані каністри на складі об'єкта;
- `empty_count` — порожні каністри на об'єкті, готові до відправки на заправку;
- `away_refill_count` — каністри, передані на заправку («на АЗС»);
- `reserve_liters` — залишок палива в окремій наземній резервній ємності (`0 <= reserve_liters < canister_volume_l`).

Загальний доступний залишок пулу та синхронізований баланс складу `FuelStock.current_balance_l`:
$$\text{Загальний залишок (л)} = \text{full\_count} \times \text{canister\_volume\_l} + \text{reserve\_liters}$$

---

## 2. Механіка «Неповна каністра → Порожня + Резервна ємність»

Коли каністра відкрита для заправки бака генератора, а в ній залишається `3–5 л` чи інший залишок:
1. Залишок зливається в **резервну ємність об'єкта** (`reserve_liters`), тому відкрита каністра одразу стає **порожньою** (`empty_count += 1`) і може бути віддана на заправку без простою тари.
2. На кожній наступній заправці генератора **паливо з резервної ємності витрачається першим**:
   - Якщо `liters <= reserve_liters`: списується виключно з резерву (`opened_canisters = 0`);
   - Якщо `liters > reserve_liters`: спочатку вичерпується весь `reserve_liters`, а на решту `need = liters - reserve_liters` відкривається $\lceil \text{need} / \text{canister\_volume\_l} \rceil$ повних каністр; надлишок потрапляє в `reserve_liters`.
   - *Приклад:* при резерві `4 л` та заправці `24 л` (номінал каністри `20 л`) списується `4 л` з резерву + відкривається `1` повна каністра (`20 л`), новий резерв = `0 л`.

---

## 3. Життєвий цикл операцій та API

Усі рухи фіксуються в журналі [`CanisterTransaction`](../backend/app/models/canister.py) зі знімками станів `before → after`:

| Операція | Ендпоінт | Зміна станів | Доступ (RBAC) |
| :--- | :--- | :--- | :--- |
| Створення / налаштування пулу | `POST /api/v1/fuel/canisters`, `PUT /api/v1/fuel/canisters/{id}` | Ініціалізація кількості, номіналу та синхронізація `FuelStock` | `fuel:configure` |
| Видалення порожнього пулу | `DELETE /api/v1/fuel/canisters/{id}` | Лише при нульовому паливному залишку | `fuel:configure` |
| Віддали на заправку (`DISPATCH_REFILL`) | `POST /api/v1/fuel/canisters/{id}/dispatch` | `empty_count -= N`, `away_refill_count += N` | `fuel:transfer` |
| Повернули порожніми (`RETURN_EMPTY`) | `POST /api/v1/fuel/canisters/{id}/return-empty` | `away_refill_count -= N`, `empty_count += N` | `fuel:transfer` |
| Привезли заправлені (`RECEIVE_REFILL`) | `POST /api/v1/fuel/canisters/{id}/receive` | `source="auto"` (спершу `away_refill_count`, далі `empty_count`) `→ full_count += N`, `+N*V` л на склад, авто-чек `FuelReceipt` | `fuel:receipt` |
| Заправка генератора (`CONSUME_TRANSFER`) | `POST /api/v1/fuel/transfer` | Резерв першим + відкриття повних каністр + перелив залишку в резерв | `fuel:transfer` |
| Прямий чек на каністровий склад | `POST /api/v1/fuel/receipt` | Контроль кратності `canister_volume_l` та наявності вільних/відправлених каністр | `fuel:receipt` |
| Системні коригування (`POOL_ADJUSTMENT`) | `POST /api/v1/adjustments` | Пряме редагування полів `CanisterPool` (`full_count`, `empty_count`, `away_refill_count`, `reserve_liters`) або авто-декомпозиція `FuelStock.current_balance_l` (в межах місткості пулу) | `audit:adjust` (`SUPERADMIN`) |
