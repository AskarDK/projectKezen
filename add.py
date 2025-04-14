from main import db, Event, app
from sqlalchemy.exc import OperationalError

def add_column():
    """Добавляет поле coordinates в таблицу Event, если его нет."""
    with app.app_context():  # 👈 Включаем контекст Flask-приложения
        try:
            inspector = db.inspect(db.engine)
            columns = [column["name"] for column in inspector.get_columns("event")]

            if "coordinates" not in columns:
                with db.engine.connect() as connection:
                    connection.execute("ALTER TABLE event ADD COLUMN coordinates TEXT;")
                    print("✅ Поле coordinates успешно добавлено в таблицу Event.")
            else:
                print("ℹ️ Поле coordinates уже существует.")

        except OperationalError as e:
            print(f"❌ Ошибка при изменении таблицы: {e}")

if __name__ == "__main__":
    add_column()
