import uuid

import openai
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta, time
from flask import send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
import logging
from sqlalchemy import func
from enum import Enum
from flask import abort, make_response
from sqlalchemy import and_, or_
from werkzeug.utils import secure_filename
from flask_cors import CORS

polls = {}



logging.basicConfig(level=logging.DEBUG)


import os

openai.api_key = "OPENAI_API_KEY"



app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"
app.config["SECRET_KEY"] = "your_secret_key"
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

login_manager = LoginManager(app)
login_manager.login_view = "login"

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

class UserLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)

    user = db.relationship("User", backref="user_likes")
    event = db.relationship("Event")  # Убираем backref="likes"

class EventActionType(Enum):
    VIEW = "view"
    LIKE = "like"
    COMMENT = "comment"
    JOIN = "join"
    LEAVE = "leave"

class EventAction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    action_type = db.Column(db.String(20), nullable=False)  # VIEW, LIKE, COMMENT, JOIN, LEAVE
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="event_actions")
    event = db.relationship("Event", backref="actions")

    def __repr__(self):
        return f"<EventAction {self.user_id} {self.action_type} {self.event_id}>"


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="comments")
    event = db.relationship("Event", backref="comments")

class EventPoll(db.Model):
    __tablename__ = 'event_poll'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question = db.Column(db.String(255), nullable=False)
    options = db.Column(db.String(500), nullable=False)  # Сохраняем варианты ответов как строку, разделенную запятыми
    votes = db.Column(db.JSON, nullable=False, default={})  # Храним словарь: {answer_id: [user_ids]}
    is_active = db.Column(db.Boolean, default=True)  # Поле для отслеживания активности опроса

    event = db.relationship('Event', backref=db.backref('polls', uselist=False))
    user = db.relationship('User', backref=db.backref('polls', lazy=True))

    def add_vote(self, option_id, user_id):
        if option_id not in self.votes:
            self.votes[option_id] = []
        self.votes[option_id].append(user_id)
        db.session.commit()

    def get_vote_count(self, option_id):
        return len(self.votes.get(option_id, []))

class Interest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("interest.id"), nullable=True)  # Для подкатегорий
    parent = db.relationship("Interest", remote_side=[id], backref="sub_interests")

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)  # Может быть NULL для чатов событий
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id], backref="messages_sent")
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref="messages_received")

class RelatedInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    interest_id = db.Column(db.Integer, db.ForeignKey("interest.id"), nullable=False)
    related_id = db.Column(db.Integer, db.ForeignKey("interest.id"), nullable=False)

    interest = db.relationship("Interest", foreign_keys=[interest_id], back_populates="related_interests")
    related = db.relationship("Interest", foreign_keys=[related_id], back_populates="related_to")

Interest.related_interests = db.relationship(
    "RelatedInterest",
    foreign_keys=[RelatedInterest.interest_id],
    back_populates="interest",
    cascade="all, delete-orphan"
)

Interest.related_to = db.relationship(
    "RelatedInterest",
    foreign_keys=[RelatedInterest.related_id],
    back_populates="related",
    cascade="all, delete-orphan"
)

class EventSurvey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    completed = db.Column(db.Boolean, default=False)
    feedback = db.Column(db.Text)
    platform_rating = db.Column(db.Integer)

    event = db.relationship('Event', backref=db.backref('survey', lazy=True))
    user = db.relationship('User', backref=db.backref('survey', lazy=True))


class UserInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    interest_id = db.Column(db.Integer, db.ForeignKey("interest.id"), nullable=False)

    user = db.relationship("User", backref="user_interests")
    interest = db.relationship("Interest")

class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="pending")  # "pending", "accepted", "declined"

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_friend_requests")
    receiver = db.relationship("User", foreign_keys=[receiver_id], backref="received_friend_requests")


friendship = db.Table(
    "friendship",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id")),
    db.Column("friend_id", db.Integer, db.ForeignKey("user.id"))
)

event_banned_users = db.Table(
    'event_banned_users',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)



class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    birth_date = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    profile_picture = db.Column(db.String(300), nullable=True, default="static/uploads/default_avatar.jpg")
    is_moderator = db.Column(db.Boolean, default=False)  # 👈 Добавляем роль
    organizer_rating = db.Column(db.Float, default=5.0)
    # Новый рейтинг как участник
    participant_rating = db.Column(db.Float, default=5.0)

    def recalculate_ratings(self):
        """
        Пересчитывает рейтинги (организатора и участника) на основе последних 100 отзывов.
        """
        # Получаем последние 100 отзывов, которые он получил как организатор
        organizer_reviews = EventReview.query.join(Event).filter(
            Event.creator == self.id
        ).order_by(EventReview.timestamp.desc()).limit(100).all()

        # Получаем последние 100 отзывов, которые он получил как участник
        participant_reviews = EventReview.query.filter(
            EventReview.user_id == self.id
        ).order_by(EventReview.timestamp.desc()).limit(100).all()

        # Вычисляем новый рейтинг организатора
        if organizer_reviews:
            total_rating = sum(r.rating for r in organizer_reviews) + (50 * 5)  # 50 отзывов 5 по умолчанию
            self.organizer_rating = round(total_rating / (len(organizer_reviews) + 50), 1)
        else:
            self.organizer_rating = 5.0  # Если отзывов нет, оставляем 5

        # Вычисляем новый рейтинг участника
        if participant_reviews:
            total_rating = sum(r.rating for r in participant_reviews) + (50 * 5)  # 50 отзывов 5 по умолчанию
            self.participant_rating = round(total_rating / (len(participant_reviews) + 50), 1)
        else:
            self.participant_rating = 5.0

        db.session.commit()

    def is_admin(self, event_id):
        event = Event.query.get(event_id)
        if not event:
            return False
        admin_ids = event.admins.split(",") if event.admins else []
        admin_ids = [int(uid.strip()) for uid in admin_ids if uid.strip().isdigit()]
        return self.id in admin_ids or self.id == event.creator

    @property
    def rating(self):
        """Вычисляет средний рейтинг организатора на основе отзывов к его ивентам."""
        total_reviews = db.session.query(func.count(EventReview.id)).join(Event).filter(
            Event.creator == self.id).scalar()
        if total_reviews == 0:
            return 0  # Если нет отзывов, рейтинг = 0

        total_rating = db.session.query(func.sum(EventReview.rating)).join(Event).filter(
            Event.creator == self.id).scalar()
        return round(total_rating / total_reviews, 1)

    # Друзья пользователя
    friends = db.relationship(
        "User",
        secondary=friendship,
        primaryjoin=(friendship.c.user_id == id),
        secondaryjoin=(friendship.c.friend_id == id),
        backref="friend_list"
    )

    def __repr__(self):
        return f"<User {self.username}>"



# Модель пользователя

event_users = db.Table(
    'event_users',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('event_id', db.Integer, db.ForeignKey('event.id'), primary_key=True)
)


class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(255), nullable=True)
    expiry_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)  # ✅ По умолчанию активно
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    user = db.relationship("User", backref="announcements")
    views = db.Column(db.Integer, default=0)  # Количество просмотров
    clicks = db.Column(db.Integer, default=0)  # Количество кликов по кнопке

class AnnouncementStats(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    announcement_id = db.Column(db.Integer, db.ForeignKey('announcement.id'), nullable=False)
    date = db.Column(db.Date, default=datetime.utcnow, nullable=False)
    views = db.Column(db.Integer, default=0, nullable=False)
    clicks = db.Column(db.Integer, default=0, nullable=False)

    announcement = db.relationship('Announcement', backref=db.backref('stats', lazy=True))

class City(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    events = db.relationship("Event", backref="city", lazy=True)


class EventStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class Event(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    user_limit = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(300), nullable=True)
    creator = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    coordinates = db.Column(db.String(50), nullable=True)  # 🔥 Добавляем поле для координат
    keywords = db.Column(db.String(300), nullable=True)
    date = db.Column(db.Date, nullable=False)  # Изменено с String на Date
    time = db.Column(db.String(20), nullable=False)
    admins = db.Column(db.String(300), nullable=True)
    users = db.Column(db.String(300), nullable=True)
    chat_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), default=EventStatus.PENDING.value)  # Новый статус
    rating = db.Column(db.Float, default=0.0)
    user_limit = db.Column(db.Integer, nullable=True)
    likes = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)  # ✅ Новое поле (по умолчанию ивент активный)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # Для сортировки
    required_rating = db.Column(db.Float, default=0.0)
    banned_users = db.relationship("User", secondary=event_banned_users, backref="banned_from_events")
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=True)


    creator_user = db.relationship("User", backref="events_created")
    participants = db.relationship("User", secondary=event_users, backref="joined_events")

    def get_admins(self):
        """Возвращает список ID админов"""
        return [int(uid) for uid in self.admins.split(",") if uid] if self.admins else []

    def __repr__(self):
        return f"<Event {self.title}>"


class EventMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", backref="event_messages")
    event = db.relationship("Event", backref="messages")

class AdminChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="admin_chat_messages")

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Кому уведомление
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Кто отправил
    message = db.Column(db.String(255), nullable=False)  # Текст уведомления
    action_type = db.Column(db.String(50), nullable=False)  # Тип (friend_request, like, message)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=True)  # Если связано с событием
    is_read = db.Column(db.Boolean, default=False)  # Прочитано или нет
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)  # Дата создания

    sender = db.relationship('User', foreign_keys=[sender_id])
    event = db.relationship('Event', foreign_keys=[event_id])

    def __repr__(self):
        return f"<Notification {self.message}>"


class EventReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="reviews")
    event = db.relationship("Event", backref="reviews")

@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.route("/get_event_stats/<int:event_id>")
@login_required
def get_event_stats(event_id):
    print(f"🔍 Запрос статистики для ивента {event_id}")
    event = Event.query.get(event_id)

    if not event:
        print(f"❌ Ошибка: Ивент {event_id} не найден!")
        return jsonify({"error": "Ивент не найден"}), 404

    views = EventAction.query.filter_by(event_id=event.id, action_type="view").count()
    likes = event.likes
    participants = len(event.participants)
    comments = Comment.query.filter_by(event_id=event.id).count()

    print(f"✅ Данные статистики: Views={views}, Likes={likes}, Participants={participants}, Comments={comments}")

    return jsonify({
        "title": event.title,
        "creator": event.creator_user.username,
        "date": event.date.strftime("%d.%m.%Y"),
        "location": event.location,
        "views": views,
        "likes": likes,
        "participants": participants,
        "comments": comments,
        "analysis": f"Уровень вовлеченности: {round((likes + participants) / views * 100, 2)}%" if views > 0 else "Недостаточно данных."
    })

@app.route("/submit_review/<int:event_id>", methods=["POST"])
@login_required
def submit_review(event_id):
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "Нет данных в запросе"}), 400

    review_text = data.get("text", "").strip()
    try:
        review_rating = int(data.get("rating", 0))
    except ValueError:
        return jsonify({"success": False, "message": "Рейтинг должен быть числом"}), 400

    if not review_text or review_rating not in range(1, 6):
        return jsonify({"success": False, "message": "Некорректные данные"}), 400

    event = Event.query.get_or_404(event_id)

    # Проверяем, что пользователь был участником или админом
    if current_user not in event.participants and str(current_user.id) not in event.admins.split(","):
        return jsonify({"success": False, "message": "Вы не участвовали в этом ивенте!"}), 403

    # Проверяем, оставлял ли пользователь уже отзыв
    existing_review = EventReview.query.filter_by(event_id=event_id, user_id=current_user.id).first()
    if existing_review:
        return jsonify({"success": False, "message": "Вы уже оставили отзыв!"}), 400

    # Сохраняем отзыв
    new_review = EventReview(event_id=event_id, user_id=current_user.id, text=review_text, rating=review_rating)
    db.session.add(new_review)
    db.session.commit()

    # 🔥 Обновляем рейтинг организатора
    organizer = User.query.get(event.creator)
    if organizer:
        organizer.recalculate_ratings()

    # 🔥 Обновляем рейтинг участника (того, кто оставил отзыв)
    current_user.recalculate_ratings()

    return jsonify({"success": True, "message": "Отзыв сохранен!"})


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))  # ✅ Новая версия


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return redirect(url_for("login"))

@app.route('/event/<int:event_id>')
@login_required
def event_detail(event_id):
    event = Event.query.get_or_404(event_id)
    creator_user = User.query.get(event.creator)
    event_datetime = datetime.combine(event.date, time.min)  # Для времени берем минимальное (00:00:00)
    show_survey = False
    current_datetime = datetime.now()

    if event_datetime < current_datetime and event.is_active:
        if event.creator == current_user.id:
            # Проверяем, прошел ли создатель опрос
            survey = EventSurvey.query.filter_by(event_id=event_id, user_id=current_user.id, completed=False).first()
            if not survey:
                show_survey = True

    if show_survey and request.method == 'POST':
        feedback = request.form.get('feedback')
        platform_rating = int(request.form.get('platform_rating'))
        survey = EventSurvey(event_id=event_id, user_id=current_user.id, feedback=feedback,
                             platform_rating=platform_rating, completed=True)
        db.session.add(survey)
        db.session.commit()
        flash('Спасибо за ваш отзыв!', 'success')


    is_creator = current_user.id == event.creator
    is_admin = current_user.is_admin(event_id)

    if not EventAction.query.filter_by(user_id=current_user.id, event_id=event.id,
                                       action_type=EventActionType.VIEW.value).first():
        new_action = EventAction(user_id=current_user.id, event_id=event.id, action_type=EventActionType.VIEW.value)
        db.session.add(new_action)
        db.session.commit()

    # Если ивент завершен, то только создатель может его просматривать
    if not event.is_active and not is_creator:
        flash("Этот ивент завершен и недоступен.", "danger")
        return redirect(url_for("home"))

    admin_ids = event.admins.split(",") if event.admins else []
    admin_users = [User.query.get(int(admin_id)) for admin_id in admin_ids if admin_id.isdigit()]
    participant_users = [user for user in event.participants if str(user.id) not in admin_ids]

    is_participant = current_user in event.participants

    # ✅ Проверяем, оставил ли пользователь отзыв
    has_reviewed = EventReview.query.filter_by(event_id=event.id, user_id=current_user.id).first() is not None

    return render_template(
        'event_detail.html',
        event=event,
        creator_user=creator_user,
        admin_users=admin_users,
        participant_users=participant_users,
        is_participant=is_participant,
        is_creator=is_creator,
        is_admin=is_admin,
        has_reviewed=has_reviewed,
        event_datetime=event_datetime,
        current_datetime=current_datetime,
        show_survey=show_survey# ✅ Передаем в шаблон
    )

@app.route("/get_friend_recommendations", methods=["POST"])
def get_friend_recommendations():
    try:
        data = request.get_json()
        selected_interest_ids = data.get("interests", [])

        if not selected_interest_ids:
            return jsonify([])  # ничего не выбрано — ничего не возвращаем

        # Ищем пользователей, у которых хотя бы один из выбранных интересов
        matched_users = db.session.query(User).join(UserInterest).filter(
            UserInterest.interest_id.in_(selected_interest_ids)
        ).distinct().limit(10).all()

        result = []
        for user in matched_users:
            result.append({
                "id": user.id,
                "username": user.username,
                "avatar": user.profile_picture or "/static/uploads/default_avatar.jpg"
            })

        return jsonify(result)

    except Exception as e:
        print("❌ Ошибка в get_friend_recommendations:", str(e))
        return jsonify({"error": str(e)}), 500


@app.route("/home")
@login_required
def home():
    search_query = request.args.get('search', '').strip()
    selected_date = request.args.get('date', '')
    selected_location = request.args.get('location', '')
    selected_categories = request.args.getlist("category")
    selected_city_id = request.args.get('city_filter', type=int)

    current_datetime = datetime.now()
    today = current_datetime.date()
    current_time_str = current_datetime.strftime("%H:%M")

    # Изначально выбираем активные события, которые ещё не прошли и одобрены (approved)
    # Добавляем фильтр, чтобы исключить события, созданные текущим пользователем
    events_query = Event.query.filter(
        Event.is_active == True,
        Event.status == EventStatus.APPROVED.value,
        or_(
            Event.date > today,
            and_(
                Event.date == today,
                Event.time >= current_time_str
            )
        ),
        Event.creator != current_user.id  # ← Новое условие, исключающее собственные события
    )

    # Добавляем фильтр: исключаем события, в которых текущий пользователь забанен
    events_query = events_query.filter(~Event.banned_users.any(User.id == current_user.id))

    parent_interests = Interest.query.filter_by(parent_id=None).order_by(Interest.name).all()
    liked_event_ids = [like.event_id for like in UserLike.query.filter_by(user_id=current_user.id).all()]
    announcements = Announcement.query.filter_by(is_active=True).order_by(Announcement.created_at.desc()).limit(5).all()
    upcoming_events = Event.query.filter(Event.date >= datetime.today().date()).order_by(Event.date.asc()).limit(
        10).all()

    # Фильтрация по категориям, дате, локации и поисковому запросу
    if selected_categories:
        conditions = [Event.keywords.like(f"%{keyword}%") for keyword in selected_categories]
        events_query = events_query.filter(or_(*conditions))

    if selected_date:
        date_obj = None
        try:
            # Предполагаем стандартный формат от input type=date (YYYY-MM-DD)
            date_obj = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except ValueError:
            try:
                # Альтернативный формат, если используется кастомный календарь (например, DD.MM.YYYY)
                date_obj = datetime.strptime(selected_date, "%d.%m.%Y").date()
            except ValueError:
                flash("Неверный формат даты. Используйте YYYY-MM-DD или DD.MM.YYYY.", "danger")
        if date_obj:
            events_query = events_query.filter(Event.date == date_obj)

    if selected_location:
        events_query = events_query.filter(Event.location == selected_location)

    if search_query:
        events_query = events_query.filter(
            or_(
                Event.title.ilike(f"%{search_query}%"),
                Event.description.ilike(f"%{search_query}%")
            )
        )

    if selected_city_id:
        events_query = events_query.filter_by(city_id=selected_city_id)

    cities = City.query.all()
    all_events = events_query.all()

    # Простейшая система рекомендаций на основе совпадения ключевых слов
    user_interests = [ui.interest.name.lower() for ui in current_user.user_interests]
    event_scores = []
    for event in all_events:
        score = 0
        if event.keywords:
            event_keywords = [kw.strip().lower() for kw in event.keywords.split(",")]
            for keyword in event_keywords:
                if keyword in user_interests:
                    score += 2  # +2 балла за каждое совпадение интересов
        event_scores.append((event, score))
    event_scores.sort(key=lambda x: (-x[1], -x[0].likes))
    recommended_events = [event[0] for event in event_scores]

    for event in recommended_events:
        event.is_liked = UserLike.query.filter_by(user_id=current_user.id, event_id=event.id).first() is not None

    soon_events = Event.query.filter(Event.date >= datetime.today().date()).order_by(Event.date.asc(),
                                                                                     Event.time.asc()).limit(10).all()

    return render_template(
        'home.html',
        events=recommended_events,
        soon_events=soon_events,
        upcoming_events=upcoming_events,
        search_query=search_query,
        selected_date=selected_date,
        selected_location=selected_location,
        announcements=announcements,
        cities=cities,
        selected_city_id=selected_city_id,
        parent_interests=parent_interests,
        selected_categories=selected_categories,
        liked_event_ids=liked_event_ids,
    get_time_left=get_time_left  # ← добавь это

    )

def get_time_left(date_obj, time_str):
    from datetime import datetime, timedelta

    try:
        event_datetime = datetime.combine(date_obj, datetime.strptime(time_str, '%H:%M').time())
        now = datetime.now()
        delta = event_datetime - now

        if delta.total_seconds() < 0:
            return "Уже прошло"

        days = delta.days
        hours = delta.seconds // 3600

        if days >= 1:
            return f"Через {days} дн."
        else:
            return f"Через {hours} ч."
    except:
        return ""

@app.route("/moderation")
@login_required
def moderation_panel():
    if not current_user.is_moderator:
        abort(403)  # Запрещаем доступ, если не модератор

    pending_events = Event.query.filter_by(status=EventStatus.PENDING.value).order_by(Event.created_at.desc()).all()

    return render_template("moderation.html", events=pending_events)

@app.route("/announcement/<int:announcement_id>")
@login_required
def announcement_detail(announcement_id):
    if not current_user.is_moderator:
        return redirect(url_for("home"))

    """Страница объявления (модераторская версия). Не увеличивает счетчик просмотров."""
    announcement = Announcement.query.get_or_404(announcement_id)

    if not current_user.is_moderator:
        abort(403)  # ❌ Запрещаем доступ обычным пользователям

    # Подсчитываем общие просмотры и клики по объявлению
    total_views = db.session.query(db.func.sum(AnnouncementStats.views)).filter_by(announcement_id=announcement.id).scalar() or 0
    total_clicks = db.session.query(db.func.sum(AnnouncementStats.clicks)).filter_by(announcement_id=announcement.id).scalar() or 0
    avg_ctr = round((total_clicks / total_views * 100), 2) if total_views > 0 else 0  # CTR = клики / просмотры * 100

    return render_template(
        "announcement_detail.html",
        announcement=announcement,
        total_views=total_views,
        total_clicks=total_clicks,
        avg_ctr=avg_ctr
    )


@app.route("/announcement_user/<int:announcement_id>")
def announcement_detail_user(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)
    return render_template("announcement_detail_user.html", announcement=announcement)


@app.route('/announcement_view/<int:announcement_id>', methods=['POST'])
@login_required
def register_view(announcement_id):
    """Фиксируем просмотр объявления, но только если оно открыто с главной страницы (/home)."""
    referrer = request.headers.get("Referer", "")

    # ✅ Засчитываем просмотры ТОЛЬКО если переход был с home.html
    if "/home" in referrer:
        today = datetime.utcnow().date()
        announcement = Announcement.query.get_or_404(announcement_id)

        # Ищем запись статистики за сегодня
        stat_entry = AnnouncementStats.query.filter_by(announcement_id=announcement.id, date=today).first()

        if not stat_entry:
            stat_entry = AnnouncementStats(announcement_id=announcement.id, date=today, views=1)
            db.session.add(stat_entry)
        else:
            stat_entry.views += 1

        db.session.commit()
        return jsonify({"success": True, "views": stat_entry.views})

    return jsonify({"success": False, "message": "Просмотр не засчитан (не с главной страницы)."})

@app.route("/announcement_click/<int:announcement_id>", methods=["POST"])
@login_required
def register_announcement_click(announcement_id):
    """Фиксируем клик по объявлению и обновляем статистику."""
    announcement = Announcement.query.get_or_404(announcement_id)
    today = datetime.utcnow().date()

    # Ищем запись статистики за сегодня
    stat_entry = AnnouncementStats.query.filter_by(announcement_id=announcement.id, date=today).first()

    if not stat_entry:
        stat_entry = AnnouncementStats(announcement_id=announcement.id, date=today, clicks=1)
        db.session.add(stat_entry)
    else:
        stat_entry.clicks += 1

    db.session.commit()

    # Подсчитываем общее количество кликов
    total_clicks = db.session.query(db.func.sum(AnnouncementStats.clicks)).filter_by(announcement_id=announcement.id).scalar() or 0

    return jsonify({"success": True, "clicks": total_clicks})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()

    if not data:
        return jsonify({"success": False, "message": "Пустой запрос"}), 400

    username = data.get("username")
    password = data.get("password")

    user = User.query.filter(func.lower(User.username) == username.lower()).first()

    if user and check_password_hash(user.password_hash, password):
        login_user(user)
        return jsonify({
            "success": True,
            "user_id": user.id,
            "username": user.username,
            "is_moderator": user.is_moderator
        })

    return jsonify({"success": False, "message": "Неверный логин или пароль"}), 401


@app.route("/announcement_click/<int:announcement_id>", methods=["POST"])
@login_required
def register_click(announcement_id):
    announcement = Announcement.query.get_or_404(announcement_id)

    today = datetime.utcnow().date()
    stat_entry = AnnouncementStats.query.filter_by(announcement_id=announcement.id, date=today).first()

    if not stat_entry:
        stat_entry = AnnouncementStats(announcement_id=announcement.id, date=today, clicks=1)
        db.session.add(stat_entry)
    else:
        stat_entry.clicks += 1

    db.session.commit()

    total_clicks = db.session.query(db.func.sum(AnnouncementStats.clicks)).filter_by(announcement_id=announcement.id).scalar() or 0

    return jsonify({"success": True, "clicks": total_clicks})

@app.route("/announcement_stats/<int:announcement_id>")
@login_required
def get_announcement_stats(announcement_id):
    today = datetime.utcnow().date()
    seven_days_ago = today - timedelta(days=6)

    stats = db.session.query(AnnouncementStats.date, db.func.sum(AnnouncementStats.views), db.func.sum(AnnouncementStats.clicks))\
        .filter(AnnouncementStats.announcement_id == announcement_id, AnnouncementStats.date >= seven_days_ago)\
        .group_by(AnnouncementStats.date)\
        .order_by(AnnouncementStats.date)\
        .all()

    dates = [(seven_days_ago + timedelta(days=i)).strftime("%d.%m") for i in range(7)]
    views = [0] * 7
    clicks = [0] * 7

    for stat in stats:
        index = (stat[0] - seven_days_ago).days
        views[index] = stat[1] or 0
        clicks[index] = stat[2] or 0

    return jsonify({"dates": dates, "views": views, "clicks": clicks})



@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.is_moderator:
            return redirect(url_for("moderation_panel"))
        return redirect(url_for("home"))

    error = None
    next_page = request.args.get("next")

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        remember = "remember" in request.form

        # ✅ Приводим к нижнему регистру и сравниваем
        user = User.query.filter(func.lower(User.username) == username.lower()).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            flash("Вход выполнен успешно!", "success")
            if user.is_moderator:
                return redirect(url_for("moderation_panel"))
            return redirect(next_page or url_for("home"))
        else:
            error = "Неправильные имя пользователя или пароль"

    return render_template("login.html", error=error)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/get_notifications", methods=["GET"])
@login_required
def get_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.timestamp.desc()).all()

    return jsonify([
        {
            "id": n.id,
            "message": n.message,
            "timestamp": n.timestamp.strftime("%H:%M"),
            "sender_avatar": n.sender.profile_picture if n.sender else None,
            "action_type": n.action_type,
            "is_read": n.is_read,
            "event_id": n.event_id,  # ✅ Теперь event_id передается в ответе
            "sender_id": n.sender.id if n.sender else None,
        }
        for n in notifications
    ])


@app.route("/mark_notifications_as_read", methods=["POST"])
@login_required
def mark_notifications_as_read():
    """Обновляет статус всех уведомлений пользователя на 'прочитанные'."""
    try:
        notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).all()

        if not notifications:
            return jsonify({"success": False, "message": "Нет новых уведомлений."})

        for notification in notifications:
            notification.is_read = True  # ✅ Меняем вручную

        db.session.commit()  # ✅ Обязательно фиксируем изменения

        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()  # Откат в случае ошибки
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/generate_description", methods=["POST"])
@login_required
def generate_description():
    try:
        data = request.get_json()
        event_title = data.get("title", "").strip()

        if not event_title:
            return jsonify({"success": False, "message": "Введите название события!"}), 400

        # Новый API-синтаксис для OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Используй gpt-4-turbo или gpt-3.5-turbo
            messages=[
                {"role": "system", "content": "Ты помощник, который помогает пользователям создавать описания мероприятий."},
                {"role": "user", "content": f"Создай краткое и привлекательное описание для мероприятия с названием: {event_title}"}
            ],
            max_tokens=500,
            temperature=0.7
        )

        generated_text = response["choices"][0]["message"]["content"].strip()

        return jsonify({"success": True, "description": generated_text})

    except Exception as e:
        return jsonify({"success": False, "message": f"Ошибка генерации: {str(e)}"}), 500


@app.route("/create_event", methods=["POST"])
@login_required
def create_event():
    try:
        # Получаем базовые данные
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        coordinates = request.form.get("coordinates", "").strip()
        city_id_str = request.form.get("city_id", "").strip()
        keywords_list = request.form.getlist("keywords")
        keywords_str = ", ".join(keywords_list) if keywords_list else None

        # Валидация обязательных полей
        if not title:
            return jsonify({"success": False, "message": "Название события обязательно"}), 400
        if not description:
            return jsonify({"success": False, "message": "Описание обязательно"}), 400
        if not location:
            return jsonify({"success": False, "message": "Адрес обязателен"}), 400
        if not date_str:
            return jsonify({"success": False, "message": "Дата обязательна"}), 400
        if not time_str:
            return jsonify({"success": False, "message": "Время обязательно"}), 400

        # Парсинг даты и времени
        try:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"success": False, "message": "Неверный формат даты. Используйте YYYY-MM-DD"}), 400

        try:
            event_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            return jsonify({"success": False, "message": "Неверный формат времени. Используйте HH:MM"}), 400

        event_datetime = datetime.combine(event_date, event_time)
        if event_datetime < datetime.now():
            return jsonify({"success": False, "message": "Событие не может начинаться в прошлом"}), 400

        # Обработка дополнительного поля "Минимальный рейтинг участника"
        required_rating_str = request.form.get("required_rating", "").strip()
        if required_rating_str:
            try:
                required_rating = float(required_rating_str)
            except ValueError:
                return jsonify({"success": False, "message": "Некорректное значение рейтинга"}), 400
            if required_rating < 0 or required_rating > 5:
                return jsonify({"success": False, "message": "Рейтинг должен быть от 0 до 5"}), 400
        else:
            required_rating = 0.0

        # Обработка максимального числа участников (необязательное поле)
        user_limit_str = request.form.get("user_limit", "").strip()
        if user_limit_str:
            try:
                user_limit = int(user_limit_str)
                if user_limit < 1:
                    raise ValueError
            except ValueError:
                return jsonify({"success": False, "message": "Максимальное количество участников должно быть числом, не меньше 1"}), 400
        else:
            user_limit = None

        # Обработка города
        try:
            city_id = int(city_id_str) if city_id_str else None
        except ValueError:
            return jsonify({"success": False, "message": "Некорректный id города"}), 400

        # Валидация координат (если указаны)
        if coordinates:
            parts = coordinates.split(",")
            if len(parts) != 2:
                return jsonify({"success": False, "message": "Неверный формат координат. Должны быть 'lat,lng'"}), 400
            try:
                lat, lng = float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                return jsonify({"success": False, "message": "Координаты должны быть числами"}), 400
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                return jsonify({"success": False, "message": "Координаты вне допустимого диапазона"}), 400

        # Обработка изображения
        image = request.files.get("event_image")
        if image and allowed_file(image.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(image.filename)}"
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image.save(image_path)
            image_path = image_path.replace("\\", "/")
        else:
            image_path = "static/uploads/default_event.jpg"

        # Создаем событие, явно устанавливая статус 'pending'
        new_event = Event(
            title=title,
            description=description,
            location=location,
            coordinates=coordinates if coordinates else None,
            date=event_date,
            time=time_str,
            keywords=keywords_str,
            creator=current_user.id,
            image=image_path,
            required_rating=required_rating,
            city_id=city_id,
            user_limit=user_limit,
            status=EventStatus.PENDING.value  # Устанавливаем статус на модерацию
        )

        db.session.add(new_event)
        db.session.commit()
        return jsonify({"success": True, "message": "Событие успешно создано!"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Ошибка: {str(e)}"}), 400

@app.route("/ban_user/<int:event_id>/<int:user_id>", methods=["POST"])
@login_required
def ban_user(event_id, user_id):
    event = Event.query.get_or_404(event_id)
    # Только создатель может блокировать пользователей
    if current_user.id != event.creator:
        return jsonify({"success": False, "message": "Нет прав для блокировки пользователей!"}), 403

    user = User.query.get_or_404(user_id)

    # Если пользователь уже заблокирован, можно вернуть сообщение
    if user in event.banned_users:
        return jsonify({"success": False, "message": "Пользователь уже заблокирован!"}), 400

    # Добавляем пользователя в список заблокированных
    event.banned_users.append(user)

    # Если пользователь уже является участником, удаляем его из участников
    if user in event.participants:
        event.participants.remove(user)

    db.session.commit()
    return jsonify({"success": True, "message": "Пользователь заблокирован для участия в этом событии!"})

@app.route("/edit_profile", methods=["POST"])
@login_required
def edit_profile():
    try:
        username = request.form.get("username")
        email = request.form.get("email")
        city = request.form.get("city")
        profile_picture = request.files.get("profile_picture")

        if username:
            current_user.username = username
        if email:
            current_user.email = email
        if city:
            current_user.city = city

        if profile_picture:
            filename = f"profile_{current_user.id}.jpg"
            profile_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            profile_picture.save(profile_path)
            current_user.profile_picture = profile_path.replace("\\", "/")  # Для Windows

        db.session.commit()
        return jsonify({"success": True, "message": "Профиль успешно обновлен!"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Ошибка: {str(e)}"})


@app.route("/get_event_chart_data/<int:event_id>")
def get_event_chart_data(event_id):
    event = Event.query.get_or_404(event_id)
    today = datetime.utcnow().date()

    # Инициализируем статистику по датам
    dates = [(today - timedelta(days=i)) for i in reversed(range(7))]
    date_labels = [d.strftime("%Y-%m-%d") for d in dates]

    # Группировка действий
    views_count = {d: 0 for d in date_labels}
    likes_count = {d: 0 for d in date_labels}

    for action in event.actions:
        action_date = action.timestamp.date().strftime("%Y-%m-%d")
        if action_date in views_count:
            if action.action_type == "view":
                views_count[action_date] += 1
            elif action.action_type == "like":
                likes_count[action_date] += 1

    return jsonify({
        "dates": date_labels,
        "views": [views_count[d] for d in date_labels],
        "likes": [likes_count[d] for d in date_labels]
    })
@app.route("/profile/<int:user_id>")
@login_required
def profile(user_id):
    user = User.query.get_or_404(user_id)
    user_events = Event.query.filter_by(creator=user.id).all()
    joined_events = user.joined_events

    current_date = datetime.utcnow().date()  # Или использовать datetime.now().date() по необходимости
    is_blocked = False
    if current_user.id != user.id:
        # Если пользователь хоть в одном событии создателя заблокирован, установим флаг
        for event in current_user.events_created:
            if user in event.banned_users:
                is_blocked = True
                break
    # Проверяем статус дружбы
    if current_user.id == user.id:
        friendship_status = "self"
    elif user in current_user.friends:
        friendship_status = "friends"
    elif FriendRequest.query.filter_by(sender_id=current_user.id, receiver_id=user.id).first():
        friendship_status = "pending"
    elif FriendRequest.query.filter_by(sender_id=user.id, receiver_id=current_user.id).first():
        friendship_status = "requested"
    else:
        friendship_status = "none"

    return render_template("profile.html", current_date=current_date, user=user, user_events=user_events, is_blocked=is_blocked, joined_events=joined_events, friendship_status=friendship_status)


@app.route("/events")
@login_required
def list_events():
    # Получаем номер страницы и количество элементов на страницу из параметров запроса
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    if per_page <= 0:
        per_page = 10  # Защита: не допускаем 0 или отрицательное значение

    # Формируем запрос (пример: выбираем активные события)
    events_query = Event.query.filter_by(is_active=True, status=EventStatus.APPROVED.value)

    total_events = events_query.count()

    # Обеспечиваем, чтобы если total_events == 0, не произошло деления на ноль при расчёте количества страниц
    total_pages = (total_events + per_page - 1) // per_page if per_page > 0 else 1

    # Пагинация с использованием offset и limit
    events = events_query.order_by(Event.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return render_template('events.html', events=events, page=page, total_pages=total_pages)

@app.route('/reset_password', methods=['POST'])
def reset_password():
    # Можно использовать request.form или request.get_json() в зависимости от способа передачи данных
    data = request.form or request.get_json()
    username = data.get('username', '').strip()
    birth_date = data.get('birthDate', '').strip()
    new_password = data.get('newPassword', '').strip()

    if not username or not birth_date or not new_password:
        flash("Все поля обязательны.", "danger")
        return redirect(url_for("login"))

    if len(new_password) < 6:
        flash("Пароль должен содержать минимум 6 символов.", "danger")
        return redirect(url_for("login"))

    # Ищем пользователя по имени и дате рождения
    user = User.query.filter_by(username=username, birth_date=birth_date).first()
    if not user:
        flash("Пользователь не найден или данные не совпадают.", "danger")
        return redirect(url_for("login"))

    # Обновляем пароль, используя безопасное хэширование
    user.password_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
    db.session.commit()

    flash("Пароль успешно изменён. Войдите с новым паролем.", "success")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        birth_date = request.form.get("birth_date")
        phone = request.form.get("phone")
        city = request.form.get("city")
        interest_ids = request.form.get("interests")
        profile_picture = request.files.get("profile_picture")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Пользователь с таким email уже существует!", "danger")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password, method="pbkdf2:sha256")

        # 📌 Если загружена картинка, сохраняем её, иначе ставим `default_avatar.jpg`
        if profile_picture and allowed_file(profile_picture.filename):
            filename = f"profile_{username}.jpg"
            profile_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            profile_picture.save(profile_path)
            profile_picture_url = profile_path.replace("\\", "/")  # Убираем обратные слэши для Windows
        else:
            profile_picture_url = "static/uploads/default_avatar.jpg"

        new_user = User(
            username=username,
            email=email,
            password_hash=hashed_password,
            first_name=first_name,
            last_name=last_name,
            birth_date=birth_date,
            phone=phone,
            city=city,
            profile_picture=profile_picture_url  # Устанавливаем аватарку
        )

        try:
            db.session.add(new_user)
            db.session.commit()

            if interest_ids:
                interest_ids_list = [int(i) for i in interest_ids.split(",") if i.isdigit()]
                for interest_id in interest_ids_list:
                    user_interest = UserInterest(user_id=new_user.id, interest_id=interest_id)
                    db.session.add(user_interest)

                db.session.commit()

            flash("Регистрация прошла успешно!", "success")
            return redirect(url_for("login"))

        except Exception as e:
            db.session.rollback()
            flash(f"Ошибка регистрации: {str(e)}", "danger")

    return render_template("register.html")


def create_notification(user_id, sender_id, message, action_type, event_id=None):
    """Создает уведомление в базе данных и отправляет его в WebSocket."""
    notification = Notification(
        user_id=user_id,
        sender_id=sender_id,
        message=message,
        action_type=action_type,
        event_id=event_id
    )
    db.session.add(notification)
    db.session.commit()

    # ✅ WebSocket-уведомление сразу в браузер
    send_browser_notification(user_id, "🔔 Новое уведомление!", message)


@app.route("/announcements")
def announcements():
    now = datetime.utcnow()
    expired = Announcement.query.filter(Announcement.expiry_date < now, Announcement.is_active == True).all()
    for ann in expired:
        ann.is_active = False
    db.session.commit()

    all_announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    if not current_user.is_moderator:
        return redirect(url_for("home"))

    return render_template("announcements.html", announcements=all_announcements)



@app.route("/add_comment/<int:event_id>", methods=["POST"])
@login_required
def add_comment(event_id):
    event = Event.query.get_or_404(event_id)

    data = request.get_json()
    comment_text = data.get("comment", "").strip()

    if not comment_text:
        return jsonify({"success": False, "message": "Комментарий не может быть пустым"}), 400

    # Сохранение комментария в БД
    comment = Comment(text=comment_text, user_id=current_user.id, event_id=event_id)
    db.session.add(comment)
    db.session.commit()

    # Отправляем уведомления организатору и админам
    recipients = [event.creator] + event.get_admins()
    for recipient_id in recipients:
        if recipient_id != current_user.id:  # Не уведомляем самого комментатора
            create_notification(
                user_id=recipient_id,
                sender_id=current_user.id,
                message=f"{current_user.username} оставил комментарий в событии '{event.title}'.",
                action_type="comment",
                event_id=event.id
            )

    return jsonify({"success": True, "comment": comment_text})


@app.route("/get_interests")
def get_interests():
    interests = Interest.query.filter_by(parent_id=None).all()
    return jsonify([{"id": i.id, "name": i.name} for i in interests])

@app.route("/check_username")
def check_username():
    username = request.args.get("username", "").strip()
    exists = User.query.filter(func.lower(User.username) == username.lower()).first() is not None
    return jsonify({"available": not exists})

@app.route("/check_email")
def check_email():
    email = request.args.get("email", "").strip()
    exists = User.query.filter(func.lower(User.email) == email.lower()).first() is not None
    return jsonify({"available": not exists})

@app.route("/check_phone")
def check_phone():
    phone = request.args.get("phone", "").strip()
    exists = User.query.filter(func.lower(User.phone) == phone.lower()).first() is not None
    return jsonify({"available": not exists})

@app.route('/get_all_interests')
def get_all_interests():
    interests = Interest.query.all()
    interest_dict = {i.id: {"id": i.id, "name": i.name, "parent_id": i.parent_id} for i in interests}

    # Формируем дерево
    result = []
    for interest in interests:
        if interest.parent_id is None:
            children = [
                {"id": child.id, "name": child.name, "parent_id": child.parent_id}
                for child in interest.sub_interests
            ]
            result.append({
                "id": interest.id,
                "name": interest.name,
                "parent_id": None,
                "children": children
            })
    return jsonify(result)


@app.route("/send_friend_request/<int:user_id>", methods=["POST"])
@login_required
def send_friend_request(user_id):
    if current_user.id == user_id:
        return jsonify({"success": False, "message": "Нельзя отправить запрос самому себе!"})

    existing_request = FriendRequest.query.filter_by(sender_id=current_user.id, receiver_id=user_id).first()
    if existing_request:
        return jsonify({"success": False, "message": "Заявка уже отправлена!"})

    new_request = FriendRequest(sender_id=current_user.id, receiver_id=user_id)
    db.session.add(new_request)
    db.session.commit()

    # Создаём уведомление
    create_notification(
        user_id=user_id,
        sender_id=current_user.id,
        message=f"{current_user.username} отправил вам запрос в друзья.",
        action_type="friend_request"
    )

    return jsonify({"success": True, "message": "Заявка отправлена!"})


@app.route("/accept_friend_request/<int:user_id>", methods=["POST"])
@login_required
def accept_friend_request(user_id):
    """Принимает запрос в друзья и удаляет уведомление"""
    request = FriendRequest.query.filter_by(sender_id=user_id, receiver_id=current_user.id).first()

    if request:
        # ✅ Добавляем в друзья
        current_user.friends.append(request.sender)
        request.sender.friends.append(current_user)

        # ✅ Удаляем запрос в друзья
        db.session.delete(request)
        db.session.commit()  # ✅ Обязательно сохраняем изменения в базе

        # ✅ Удаляем уведомление
        Notification.query.filter_by(user_id=current_user.id, sender_id=user_id, action_type="friend_request").delete()
        db.session.commit()

        # ✅ Создаем новое уведомление о принятии заявки
        create_notification(
            user_id=user_id,
            sender_id=current_user.id,
            message=f"{current_user.username} принял вашу заявку в друзья.",
            action_type="friend_accepted"
        )

        return jsonify({"success": True})

    return jsonify({"success": False, "message": "Заявка не найдена!"})





@app.route("/decline_friend_request/<int:user_id>", methods=["POST"])
@login_required
def decline_friend_request(user_id):
    """Отклоняет запрос в друзья и удаляет уведомление"""
    request = FriendRequest.query.filter_by(sender_id=user_id, receiver_id=current_user.id).first()

    if request:
        db.session.delete(request)
        db.session.commit()  # ✅ Фиксируем удаление

        # ✅ Удаляем уведомление
        Notification.query.filter_by(user_id=current_user.id, sender_id=user_id, action_type="friend_request").delete()
        db.session.commit()

        return jsonify({"success": True})

    return jsonify({"success": False, "message": "Заявка не найдена!"})


@app.route("/block_user/<int:user_id>", methods=["POST"])
@login_required
def block_user(user_id):
    if current_user.id == user_id:
        return jsonify({"success": False, "message": "Нельзя заблокировать себя"}), 400

    # Получаем пользователя, которого нужно заблокировать
    user_to_block = User.query.get_or_404(user_id)

    # Проходим по всем событиям, где текущий пользователь — создатель
    events = Event.query.filter_by(creator=current_user.id).all()
    updated = False
    for event in events:
        banned_ids = [u.id for u in event.banned_users]
        if user_id not in banned_ids:
            event.banned_users.append(user_to_block)
            # Если пользователь является участником, удаляем его
            if user_to_block in event.participants:
                event.participants.remove(user_to_block)
            updated = True

    if updated:
        db.session.commit()
        return jsonify({"success": True, "message": "Пользователь заблокирован во всех ваших событиях"})
    else:
        return jsonify({"success": False, "message": "Пользователь уже заблокирован"}), 400


@app.route("/unblock_user/<int:user_id>", methods=["POST"])
@login_required
def unblock_user(user_id):
    user_to_unblock = User.query.get_or_404(user_id)
    events = Event.query.filter_by(creator=current_user.id).all()
    updated = False
    for event in events:
        if user_to_unblock in event.banned_users:
            event.banned_users.remove(user_to_unblock)
            updated = True

    if updated:
        db.session.commit()
        return jsonify({"success": True, "message": "Пользователь разблокирован во всех ваших событиях"})
    else:
        return jsonify({"success": False, "message": "Пользователь не заблокирован"}), 400


@app.route("/get_messages/<int:user_id>", methods=["GET"])
@login_required
def get_messages(user_id):
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()

    return jsonify({"messages": [
        {
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "text": msg.text,
            "timestamp": msg.timestamp.strftime("%H:%M")
        }
        for msg in messages
    ]})


@app.route('/my_events')
@login_required
def my_events():
    current_date = date.today()
    # Предполагаем, что event_users — это таблица связи между Event и User,
    # а в модели Event определён relationship participants через эту таблицу
    joined_events = (
        Event.query
        .join(event_users, Event.id == event_users.c.event_id)
        .filter(event_users.c.user_id == current_user.id)
        .all()
    )
    return render_template("my_events.html", joined_events=joined_events, current_date=current_date)


@app.route("/join_event/<int:event_id>", methods=["POST"])
@login_required
def join_event(event_id):
    event = Event.query.get_or_404(event_id)

    # Проверяем, не забанен ли пользователь (см. следующий пункт)
    if current_user in event.banned_users:
        return jsonify({"success": False, "message": "Вы забанены для участия в этом событии."}), 403

    # Проверяем рейтинг пользователя
    if current_user.participant_rating < event.required_rating:
        return jsonify({"success": False, "message": "Ваш рейтинг ниже требуемого!"}), 200

    # Проверяем максимальное количество участников, если задано
    if event.user_limit is not None and len(event.participants) >= event.user_limit:
        return jsonify({"success": False, "message": "Достигнут максимум участников для этого события."}), 400

    if current_user not in event.participants:
        event.participants.append(current_user)
        new_action = EventAction(user_id=current_user.id, event_id=event.id, action_type=EventActionType.JOIN.value)
        db.session.add(new_action)
        db.session.commit()

    return jsonify({"success": True, "message": "Вы успешно вступили!"})

@app.route("/create_announcement")
@login_required
def create_announcement():
    if not current_user.is_moderator:
        return redirect(url_for("home"))
    return render_template("create_announcement.html")


@app.route("/create_announcement", methods=["POST"])
@login_required
def submit_announcement():
    if not current_user.is_moderator:
        return jsonify({"success": False, "message": "У вас нет прав"}), 403

    title = request.form.get("title")
    description = request.form.get("description")
    type_ = request.form.get("type")
    expiry_date = request.form.get("expiry_date")

    if not title or not description or not type_ or not expiry_date:
        return jsonify({"success": False, "message": "Заполните все поля"}), 400

    try:
        expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d").date()

        if expiry_date < datetime.utcnow().date():
            return jsonify({"success": False, "message": "Дата истечения должна быть в будущем"}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Некорректная дата"}), 400

    image_filename = None
    if "image" in request.files and request.files["image"].filename:
        image = request.files["image"]
        filename = f"{uuid.uuid4().hex}_{secure_filename(image.filename)}"  # Уникальное имя файла

        # ✅ Создаём папку, если её нет
        upload_folder = os.path.join(app.static_folder, "uploads", "announcements")
        os.makedirs(upload_folder, exist_ok=True)

        image_path = os.path.join(upload_folder, filename)
        image.save(image_path)

        # Сохраняем относительный путь
        image_filename = f"uploads/announcements/{filename}"

    try:
        announcement = Announcement(
            title=title,
            description=description,
            type=type_,
            expiry_date=expiry_date,
            image=image_filename,
            user_id=current_user.id,
            created_at=datetime.utcnow(),
            is_active=True  # ✅ Объявление теперь сразу активное
        )

        db.session.add(announcement)
        db.session.commit()

        return jsonify({"success": True, "message": "Объявление опубликовано!"})

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Ошибка базы данных: {str(e)}"}), 500

@app.route("/toggle_announcement/<int:announcement_id>", methods=["POST"])
@login_required
def toggle_announcement(announcement_id):
    if not current_user.is_moderator:
        return jsonify({"success": False, "message": "Нет прав"}), 403

    announcement = Announcement.query.get_or_404(announcement_id)

    if not announcement.is_active:
        # Активация требует новую дату
        new_date_str = request.json.get("expiry_date", "")
        try:
            new_expiry_date = datetime.strptime(new_date_str, "%Y-%m-%d").date()
            if new_expiry_date <= datetime.utcnow().date():
                return jsonify({"success": False, "message": "Дата должна быть в будущем"}), 400
            announcement.expiry_date = new_expiry_date
            announcement.is_active = True
        except ValueError:
            return jsonify({"success": False, "message": "Неверный формат даты"}), 400
    else:
        # Просто деактивируем
        announcement.is_active = False

    db.session.commit()
    return jsonify({"success": True, "message": "Статус обновлён!", "is_active": announcement.is_active})


@app.route("/leave_event/<int:event_id>", methods=["POST"])
@login_required
def leave_event(event_id):
    event = Event.query.get_or_404(event_id)

    if current_user in event.participants:
        event.participants.remove(current_user)
        db.session.commit()

        # Уведомление организатору
        create_notification(
            user_id=event.creator,
            sender_id=current_user.id,
            message=f"{current_user.username} покинул ваше событие '{event.title}'.",
            action_type="leave_event",
            event_id=event.id
        )

    return jsonify({"success": True})

@app.route("/delete_announcement/<int:announcement_id>", methods=["POST"])
@login_required
def delete_announcement(announcement_id):
    if not current_user.is_moderator:
        return jsonify({"success": False, "message": "Нет прав"}), 403

    announcement = Announcement.query.get_or_404(announcement_id)
    db.session.delete(announcement)
    db.session.commit()

    return jsonify({"success": True, "message": "Объявление удалено!"})


@app.route("/delete_event/<int:event_id>", methods=["POST"])
@login_required
def delete_event(event_id):
    """Удаляет ивент (отмечает как неактивный)"""
    if not current_user.is_moderator:
        return jsonify({"success": False, "message": "Доступ запрещён!"}), 403

    event = Event.query.get_or_404(event_id)
    if not event:
        return jsonify({"success": False, "message": "Ивент не найден!"}), 404

    try:
        event.is_active = False
        db.session.commit()
        return jsonify({"success": True, "message": "Ивент успешно удалён!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Ошибка: {str(e)}"}), 500


@app.route("/restore_event/<int:event_id>", methods=["POST"])
@login_required
def restore_event(event_id):
    """Восстанавливает ивент (делает активным)"""
    if not current_user.is_moderator:
        return jsonify({"success": False, "message": "Доступ запрещён!"}), 403

    event = Event.query.get_or_404(event_id)
    if not event:
        return jsonify({"success": False, "message": "Ивент не найден!"}), 404

    try:
        event.is_active = True
        db.session.commit()
        return jsonify({"success": True, "message": "Ивент успешно восстановлен!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Ошибка: {str(e)}"}), 500


@app.route("/update_event/<int:event_id>", methods=["POST"])
@login_required
def update_event(event_id):
    event = Event.query.get_or_404(event_id)

    if event.creator != current_user.id:
        return jsonify({"success": False, "message": "Нет прав на редактирование!"}), 403

    data = request.get_json()
    event.title = data.get("title", event.title)
    event.description = data.get("description", event.description)
    event.location = data.get("location", event.location)
    event.date = datetime.strptime(data.get("date"), "%Y-%m-%d").date() if data.get("date") else event.date
    event.time = data.get("time", event.time)

    try:
        required_rating = float(data.get("required_rating", 0))
        if required_rating < 0 or required_rating > 5:
            raise ValueError
        event.required_rating = required_rating
    except ValueError:
        return jsonify({"success": False, "message": "Некорректное значение рейтинга!"}), 400

    db.session.commit()
    return jsonify({"success": True, "message": "Ивент обновлён!"})


@app.route("/set_rating_restriction/<int:event_id>", methods=["POST"])
@login_required
def set_rating_restriction(event_id):
    event = Event.query.get_or_404(event_id)

    if event.creator != current_user.id:
        return jsonify({"success": False, "message": "Нет прав!"}), 403

    data = request.get_json()
    required_rating = data.get("required_rating", 0)

    try:
        required_rating = float(required_rating)
        if required_rating < 0 or required_rating > 5:
            raise ValueError
    except ValueError:
        return jsonify({"success": False, "message": "Некорректное значение рейтинга!"}), 400

    event.required_rating = required_rating
    db.session.commit()
    return jsonify({"success": True, "message": "Ограничение по рейтингу установлено!"})


@app.route("/send_chat_message", methods=["POST"])
@login_required
def send_chat_message():
    data = request.get_json()
    event_id = data.get("event_id")
    message = data.get("message")

    event = Event.query.get(event_id)
    if not event:
        return jsonify({"success": False, "message": "Ивент не найден!"}), 404

    new_message = Message(
        sender_id=current_user.id,
        event_id=event_id,  # ❌ Ошибка: event_id нет в Message
        text=data["text"]
    )

    db.session.add(new_message)
    db.session.commit()

    return jsonify({"success": True})


def send_browser_notification(user_id, title, message):
    socketio.emit(f"notification_{user_id}", {"title": title, "message": message}, namespace="/")

@app.route("/send_test_notification")
@login_required
def send_test_notification():
    send_browser_notification(current_user.id, "🔥 Новое уведомление", "Это тестовое уведомление!")
    return jsonify({"success": True})



@app.route("/make_admin/<int:event_id>/<int:user_id>", methods=["POST"])
@login_required
def make_admin(event_id, user_id):
    event = Event.query.get_or_404(event_id)

    if current_user.id != event.creator:
        return jsonify({"success": False, "message": "Нет прав!"}), 403

    user = User.query.get_or_404(user_id)

    admin_ids = event.get_admins()
    if user_id not in admin_ids:
        admin_ids.append(user_id)
        event.admins = ",".join(map(str, admin_ids))

    db.session.commit()

    create_notification(
        user_id=user.id,
        sender_id=current_user.id,
        message=f"Вы назначены администратором события '{event.title}'.",
        action_type="admin_assigned",
        event_id=event.id
    )

    return jsonify({"success": True, "message": "Пользователь стал админом!"})


@app.route("/make_participant/<int:event_id>/<int:user_id>", methods=["POST"])
@login_required
def make_participant(event_id, user_id):
    event = Event.query.get_or_404(event_id)

    if current_user.id != event.creator:
        return jsonify({"success": False, "message": "Нет прав!"}), 403

    user = User.query.get_or_404(user_id)

    # Получаем текущих админов
    admin_ids = event.get_admins()

    if user_id in admin_ids:
        admin_ids.remove(user_id)
        event.admins = ",".join(map(str, admin_ids)) if admin_ids else None

    db.session.commit()

    return jsonify({"success": True, "message": "Пользователь понижен до участника!"})

@app.route("/get_event/<int:event_id>", methods=["GET"])
@login_required
def get_event(event_id):
    event = Event.query.get_or_404(event_id)
    return jsonify({
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "image": event.image if event.image else None,
        "location": event.location,
        "date": event.date.strftime("%Y-%m-%d"),
        "time": event.time,
        "creator": event.creator_user.username
    })


@app.route("/get_event_participants/<int:event_id>")
@login_required
def get_event_participants(event_id):
    event = Event.query.get_or_404(event_id)

    all_participants = event.participants
    admin_ids = event.admins.split(",") if event.admins else []

    admin_users = []
    participant_users = []

    for user in all_participants:
        user_data = {
            "id": user.id,
            "username": user.username,
            "profile_picture": user.profile_picture or "default_avatar.jpg"
        }
        if str(user.id) in admin_ids:
            admin_users.append(user_data)
        else:
            participant_users.append(user_data)

    return jsonify({
        "creator": {
            "id": event.creator,
            "username": User.query.get(event.creator).username,
            "profile_picture": User.query.get(event.creator).profile_picture or "default_avatar.jpg"
        },
        "admins": admin_users,
        "participants": participant_users,
        "is_creator": current_user.id == event.creator,
        "is_admin": current_user.is_admin(event_id)   # Добавлено
    })


@app.route("/send_message", methods=["POST"])
@login_required
def send_message():
    data = request.get_json()
    receiver_id = data.get("receiver_id")
    text = data.get("text", "").strip()

    if not receiver_id or not text:
        return jsonify({"success": False, "message": "Ошибка! Получатель или текст пуст."}), 400

    # ✅ Создаём личное сообщение
    new_message = Message(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        text=text
    )

    db.session.add(new_message)
    db.session.commit()

    # 📢 **Отправляем сообщение через WebSocket**
    socketio.emit(f"private_message_{receiver_id}", {
        "sender_id": current_user.id,
        "text": text,
        "timestamp": new_message.timestamp.strftime("%H:%M")
    }, namespace="/")

    @socketio.on("send_private_message", namespace="/")
    def handle_private_message(data):
        sender_id = data.get("sender_id")
        receiver_id = data.get("receiver_id")
        text = data.get("text")

        if not sender_id or not receiver_id or not text:
            return

        socketio.emit(f"private_message_{receiver_id}", {
            "sender_id": sender_id,
            "text": text
        }, namespace="/")

    # 📢 Отправляем уведомление
    create_notification(
        user_id=receiver_id,
        sender_id=current_user.id,
        message=f"{current_user.username}: {text}",
        action_type="message"
    )

    return jsonify({"success": True})




@app.route("/remove_friend/<int:user_id>", methods=["POST"])
@login_required
def remove_friend(user_id):
    friend = User.query.get(user_id)
    if not friend:
        return jsonify({"success": False, "message": "Пользователь не найден!"})

    if friend not in current_user.friends:
        return jsonify({"success": False, "message": "Вы не друзья!"})

    # ✅ Удаляем связь из таблицы "friendship"
    db.session.execute(friendship.delete().where(
        ((friendship.c.user_id == current_user.id) & (friendship.c.friend_id == friend.id)) |
        ((friendship.c.user_id == friend.id) & (friendship.c.friend_id == current_user.id))
    ))

    db.session.commit()

    # 📢 Отправляем уведомление другу
    create_notification(
        user_id=friend.id,
        sender_id=current_user.id,
        message=f"{current_user.username} удалил вас из друзей.",
        action_type="friend_remove"
    )

    return jsonify({"success": True, "message": "Пользователь удалён из друзей!"})


@app.route("/get_related_interests")
def get_related_interests():
    parent_id = request.args.get("parent_id")
    sub_interests = Interest.query.filter_by(parent_id=parent_id).all()
    return jsonify([{"id": i.id, "name": i.name} for i in sub_interests])

@app.route("/support_chat", methods=["POST"])
def support_chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "")

        if not user_message:
            return jsonify({"reply": "Пожалуйста, напишите что-нибудь!"})

        # Запрос к OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты - умный помощник поддержки KEZEN, отвечай дружелюбно и профессионально, по делу. Не длинно, четко и коротко"},
                {"role": "user", "content": user_message}
            ]
        )

        bot_reply = response["choices"][0]["message"]["content"].strip()

        return jsonify({"reply": bot_reply})

    except Exception as e:
        return jsonify({"reply": f"Ошибка: {str(e)}"}), 500

@app.route("/remove_participant/<int:event_id>/<int:user_id>", methods=["POST"])
@login_required
def remove_participant(event_id, user_id):
    """Создатель может удалить любого участника, а админ - только обычного участника"""
    event = Event.query.get_or_404(event_id)
    user = User.query.get_or_404(user_id)

    if current_user.id != event.creator and not current_user.is_admin(event_id):
        return jsonify({"success": False, "message": "Нет прав!"}), 403

    if user.id == event.creator:
        return jsonify({"success": False, "message": "Нельзя удалить создателя!"}), 400

    admin_ids = event.get_admins()
    if current_user.is_admin(event_id) and str(user.id) in admin_ids:
        return jsonify({"success": False, "message": "Админ не может удалить другого админа!"}), 403

    event.participants.remove(user)

    if str(user.id) in admin_ids:
        admin_ids.remove(str(user.id))
        event.admins = ",".join(admin_ids) if admin_ids else None

    db.session.commit()
    return jsonify({"success": True, "message": "Пользователь удалён!"})

@app.route("/moderation/events")
@login_required
def moderation_events():
    if not current_user.is_admin:  # Проверяем, что пользователь - модератор
        abort(403)

    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template("moderation_events.html", events=events)


@app.route("/send_event_message/<int:event_id>", methods=["POST"])
@login_required
def send_event_message(event_id):
    """Отправка сообщения в ивент (через fetch)"""
    data = request.get_json()
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"success": False, "message": "Сообщение не может быть пустым"}), 400

    event = Event.query.get_or_404(event_id)

    new_message = EventMessage(sender_id=current_user.id, event_id=event.id, text=text)
    db.session.add(new_message)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": {
            "user_id": current_user.id,
            "username": current_user.username,
            "text": text,
            "timestamp": new_message.timestamp.strftime("%H:%M")
        }
    })
@app.route("/events_location")
def events_location():
    # Получаем события, у которых есть координаты
    today = datetime.utcnow().date()
    events = Event.query.filter(
        Event.coordinates.isnot(None),
        Event.is_active == True,
        Event.date >= today
    ).all()

    # Преобразуем объекты в JSON-совместимый формат (словарь)
    events_data = []
    for event in events:
        # Проверяем, является ли date и time объектами datetime или уже строками
        event_date = event.date if isinstance(event.date, str) else event.date.strftime("%Y-%m-%d") if event.date else None
        event_time = event.time if isinstance(event.time, str) else event.time.strftime("%H:%M") if event.time else None

        events_data.append({
            "id": event.id,
            "title": event.title,
            "location": event.location,
            "coordinates": event.coordinates,  # Пример: "43.2567,76.9286"
            "date": event_date,
            "time": event_time,
            "image": event.image or "https://via.placeholder.com/100"
        })

    return render_template("events_location.html", events=events_data)


@app.route("/get_event_messages/<int:event_id>")
@login_required
def get_event_messages(event_id):
    messages = EventMessage.query.filter_by(event_id=event_id).order_by(EventMessage.timestamp.asc()).all()

    messages_data = []
    for msg in messages:
        user = msg.sender  # ← вот здесь, не msg.user
        messages_data.append({
            "user_id": user.id,
            "username": user.username,
            "text": msg.text,
            "timestamp": msg.timestamp.strftime("%H:%M"),
            "profile_picture": url_for('uploaded_file', filename=user.profile_picture.split('/')[
                -1]) if user.profile_picture else url_for('static', filename='uploads/default_avatar.jpg')
        })

    return jsonify(messages_data)


@app.route("/send_admin_message/<int:event_id>", methods=["POST"])
@login_required
def send_admin_message(event_id):
    """Отправка сообщения в админский чат и сохранение в БД"""
    if not current_user.is_admin(event_id):
        return jsonify({"success": False, "message": "Нет прав!"}), 403

    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"success": False, "message": "Сообщение не может быть пустым"}), 400

    try:
        # ✅ Сохраняем сообщение в базу
        new_message = AdminChatMessage(event_id=event_id, user_id=current_user.id, text=text)
        db.session.add(new_message)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": {
                "user_id": new_message.user_id,
                "username": current_user.username,
                "text": new_message.text,
                "timestamp": new_message.timestamp.strftime("%H:%M")
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Ошибка при сохранении в БД: {str(e)}"}), 500

@app.route("/get_admin_messages/<int:event_id>", methods=["GET"])
@login_required
def get_admin_messages(event_id):
    """Получение всех сообщений админского чата"""
    if not current_user.is_admin(event_id):
        return jsonify({"success": False, "message": "Нет доступа"}), 403

    try:
        messages = AdminChatMessage.query.filter_by(event_id=event_id).order_by(AdminChatMessage.timestamp.asc()).all()
        return jsonify([
            {
                "user_id": msg.user_id,
                "username": msg.user.username,
                "text": msg.text,
                "timestamp": msg.timestamp.strftime("%H:%M"),
                "profile_picture": url_for('uploaded_file', filename=msg.user.profile_picture.split('/')[-1]) if msg.user.profile_picture else url_for('static', filename='uploads/default_avatar.jpg')
            }
            for msg in messages
        ])
    except Exception as e:
        return jsonify({"success": False, "message": f"Ошибка при получении сообщений: {str(e)}"}), 500


@app.route("/complete_event/<int:event_id>", methods=["POST"])
@login_required
def complete_event(event_id):
    """Маршрут завершения ивента и отправки уведомлений участникам."""
    event = Event.query.get_or_404(event_id)

    # ✅ Проверяем, что только создатель может завершить ивент
    if event.creator != current_user.id:
        return jsonify({"success": False, "message": "У вас нет прав завершить этот ивент."}), 403

    # ✅ Меняем статус на завершенный
    event.is_active = False
    db.session.commit()

    # ✅ Получаем всех участников и админов
    participants = event.participants
    admin_ids = event.get_admins()
    admins = [User.query.get(admin_id) for admin_id in admin_ids]

    all_users = set(participants + admins)  # Убираем дубликаты

    # ✅ Отправляем уведомления всем
    for user in all_users:
        create_notification(
            user_id=user.id,
            sender_id=event.creator,
            message=f"Событие '{event.title}' завершено! Вы можете оставить отзыв.",
            action_type="event_completed",
            event_id=event.id  # ✅ Передаём ID события для кнопки "Оставить отзыв"
        )

        # ✅ WebSocket-уведомление
        send_browser_notification(
            user.id,
            "🎉 Событие завершено!",
            f"Событие '{event.title}' завершено! Вы можете оставить отзыв."
        )

    return jsonify({"success": True, "message": "Ивент завершен! Уведомления отправлены."})

@app.route("/like_event/<int:event_id>", methods=["POST"])
@login_required
def like_event(event_id):
    event = Event.query.get_or_404(event_id)
    existing_like = UserLike.query.filter_by(user_id=current_user.id, event_id=event_id).first()

    if existing_like:
        db.session.delete(existing_like)
        event.likes -= 1
        liked = False
    else:
        new_like = UserLike(user_id=current_user.id, event_id=event_id)
        db.session.add(new_like)
        event.likes += 1
        liked = True

        # Логируем лайк
        new_action = EventAction(user_id=current_user.id, event_id=event.id, action_type=EventActionType.LIKE.value)
        db.session.add(new_action)

    db.session.commit()
    return jsonify({"likes": event.likes, "liked": liked})


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


def like_post(post, user):
    print(f"🚀 Отправка уведомления о лайке {user.username} -> {post.user_id}")
    create_notification(post.user_id, user.id, f"{user.username} поставил лайк на ваш пост.")

def send_message(from_user, to_user, text):
    print(f"🚀 Отправка уведомления о сообщении {from_user.username} -> {to_user.username}")
    create_notification(to_user.id, from_user.id, f"{from_user.username} отправил вам сообщение.")

def notify_event_status(event, approved):
    message = f"Ваш ивент '{event.title}' был {'одобрен' if approved else 'отклонён'} модератором."
    create_notification(user_id=event.creator, sender_id=None, message=message, action_type="event_status")

@app.route("/approve_event/<int:event_id>", methods=["POST"])
@login_required
def approve_event(event_id):
    event = Event.query.get_or_404(event_id)
    event.status = EventStatus.APPROVED.value
    db.session.commit()
    notify_event_status(event, True)
    return jsonify({"success": True, "message": "Ивент одобрен!"})

@app.route("/reject_event/<int:event_id>", methods=["POST"])
@login_required
def reject_event(event_id):
    event = Event.query.get_or_404(event_id)
    event.status = EventStatus.REJECTED.value
    db.session.commit()
    notify_event_status(event, False)
    return jsonify({"success": True, "message": "Ивент отклонён!"})



@socketio.on("join_event_room")
def join_event_room(data):
    try:
        print("📩 Получен `join_event_room`:", data)

        event_id = data.get("event_id")
        user_id = data.get("user_id")

        if not event_id or not user_id:
            print(f"❌ Ошибка: event_id={event_id}, user_id={user_id} (не определены)")
            return

        room = f"event_chat_{event_id}"
        join_room(room)
        print(f"✅ Пользователь {user_id} присоединился к комнате {room}")

        emit("room_joined", {"message": f"Вы подключены к {room}"}, room=room)

    except Exception as e:
        print(f"❌ Ошибка в join_event_room: {e}")


@socketio.on("join_admin_chat")
def join_admin_chat(data):
    """Пользователь подключается к комнате админов"""
    event_id = data.get("event_id")
    room = f"admin_chat_{event_id}"  # ✅ Исправленный room
    if current_user.is_authenticated and current_user.is_admin(event_id):
        join_room(room)
        print(f"👑 {current_user.username} присоединился к {room}")

@socketio.on("send_event_message")
def handle_send_event_message(data):
    event_id = data.get("event_id")
    text = data.get("text", "").strip()

    if not text:
        print("❌ Ошибка: пустой текст!")
        return

    event = Event.query.get(event_id)
    if not event:
        print(f"❌ Ошибка: событие {event_id} не найдено!")
        return

    print(f"🔥 Сервер получил сообщение: {current_user.username}: {text} в {event_id}")

    new_message = EventMessage(sender_id=current_user.id, event_id=event.id, text=text)
    db.session.add(new_message)
    db.session.commit()

    room = f"event_chat_{event_id}"

    print(f"📢 Рассылаем сообщение в комнату {room}...")

    # Отправляем сообщение ВСЕМ пользователям в комнате
    emit("receive_event_message", {
        "user_id": current_user.id,
        "username": current_user.username,
        "text": text,
        "timestamp": new_message.timestamp.strftime("%H:%M")
    }, room=room, broadcast=True)

@socketio.on_error_default
def default_error_handler(e):
    print(f"❌ Ошибка WebSocket: {str(e)}")

@socketio.on("send_admin_message")
def handle_admin_message(data):
    event_id = data.get("event_id")
    text = data.get("text")

    if not current_user.is_authenticated or not current_user.is_admin(event_id):
        return

    message = AdminChatMessage(event_id=event_id, user_id=current_user.id, text=text)
    db.session.add(message)
    db.session.commit()

    emit("receive_admin_message", {
        "user_id": current_user.id,
        "username": current_user.username,
        "text": text,
        "timestamp": message.timestamp.isoformat()
    }, room=f"admin_chat_{event_id}")

port = int(os.environ.get("PORT", 5000))  # 5000 — дефолт для локального запуска

socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        # Вот сюда перенеси запросы к БД
        notifications = Notification.query.all()
        for n in notifications:
            print(n.id, n.user_id, n.message, n.is_read, n.timestamp)

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)


