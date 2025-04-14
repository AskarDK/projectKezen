from graphviz import Digraph

output_path = "diagram_final"

# === Таблицы ===
tables = {
    "user": ["id", "username", "email", "password_hash", "first_name", "last_name", "birth_date", "phone", "city", "profile_picture", "is_moderator", "organizer_rating", "participant_rating"],
    "event": ["id", "title", "description", "creator", "city_id", "date", "time", "location", "users", "admins", "user_limit", "keywords", "rating", "required_rating", "likes", "status", "image", "is_active", "coordinates", "chat_id", "created_at"],
    "admin_chat_message": ["id", "event_id", "user_id", "text", "timestamp"],
    "announcement": ["id", "user_id", "title", "description", "image", "created_at", "expiry_date", "is_active", "clicks", "views", "type"],
    "announcement_stats": ["id", "announcement_id", "date", "clicks", "views"],
    "comment": ["id", "event_id", "user_id", "text", "created_at"],
    "event_action": ["id", "event_id", "user_id", "action_type", "timestamp"],
    "event_message": ["id", "event_id", "sender_id", "text", "timestamp"],
    "event_review": ["id", "event_id", "user_id", "rating", "text", "timestamp"],
    "event_users": ["event_id", "user_id"],
    "friend_request": ["id", "sender_id", "receiver_id", "status"],
    "friendship": ["user_id", "friend_id"],
    "interest": ["id", "name", "parent_id"],
    "message": ["id", "sender_id", "receiver_id", "text", "timestamp"],
    "notification": ["id", "user_id", "sender_id", "event_id", "action_type", "message", "timestamp", "is_read"],
    "related_interest": ["id", "interest_id", "related_id"],
    "user_interest": ["id", "user_id", "interest_id"],
    "user_like": ["id", "user_id", "event_id"],
    "city": ["id", "name"]
}

# === Связи: (from_table, from_card, to_card, to_table, label) ===
relations = [
    ("user", "1", "M", "event", "creator"),
    ("event", "1", "M", "comment", "event_id"),
    ("user", "1", "M", "comment", "user_id"),
    ("event", "1", "M", "event_users", "event_id"),
    ("user", "1", "M", "event_users", "user_id"),
    ("event", "1", "M", "user_like", "event_id"),
    ("user", "1", "M", "user_like", "user_id"),
    ("interest", "1", "M", "user_interest", "interest_id"),
    ("user", "1", "M", "user_interest", "user_id"),
    ("city", "1", "M", "event", "city_id"),
    ("user", "1", "M", "announcement", "user_id"),
    ("announcement", "1", "M", "announcement_stats", "announcement_id"),
    ("user", "1", "M", "message", "sender_id"),
    ("user", "1", "M", "message", "receiver_id"),
    ("event", "1", "M", "notification", "event_id"),
    ("user", "1", "M", "notification", "user_id"),
    ("user", "1", "M", "notification", "sender_id"),
    ("interest", "1", "M", "related_interest", "interest_id"),
    ("interest", "1", "M", "related_interest", "related_id"),
    ("user", "1", "M", "friend_request", "sender_id"),
    ("user", "1", "M", "friend_request", "receiver_id"),
    ("user", "1", "M", "friendship", "user_id"),
    ("user", "1", "M", "friendship", "friend_id"),
    ("user", "1", "M", "event_review", "user_id"),
    ("event", "1", "M", "event_review", "event_id"),
    ("user", "1", "M", "event_message", "sender_id"),
    ("event", "1", "M", "event_message", "event_id"),
    ("user", "1", "M", "event_action", "user_id"),
    ("event", "1", "M", "event_action", "event_id"),
    ("user", "1", "M", "admin_chat_message", "user_id"),
    ("event", "1", "M", "admin_chat_message", "event_id"),
]

# === Инициализация графа ===
dot = Digraph(comment='ER Diagram')
dot.attr(rankdir='LR', splines='ortho', nodesep='0.8', ranksep='0.9', fontsize='12', fontname="Arial")

# === Логические кластеры (группы)
clusters = {
    'city_block': ['city'],
    'event_block': ['event', 'event_users', 'event_review', 'event_action', 'event_message', 'comment', 'admin_chat_message'],
    'user_block': ['user', 'friend_request', 'friendship', 'message', 'user_like'],
    'interest_block': ['interest', 'user_interest', 'related_interest'],
    'announcement_block': ['announcement', 'announcement_stats', 'notification']
}

# === Рисуем кластеры
for cluster_name, table_list in clusters.items():
    with dot.subgraph(name=f'cluster_{cluster_name}') as c:
        c.attr(label=cluster_name.replace('_', ' ').title(), style='dashed', color='gray')
        for table in table_list:
            if table not in tables:
                continue
            fields = tables[table]
            label = f"<<TABLE BORDER='1' CELLBORDER='1' CELLSPACING='0'>"
            label += f"<TR><TD BGCOLOR='lightblue'><B>{table}</B></TD></TR>"
            for field in fields:
                label += f"<TR><TD ALIGN='LEFT'>{field}</TD></TR>"
            label += "</TABLE>>"
            c.node(table, label=label, shape="plaintext")

# === Остальные таблицы без группы
grouped_tables = {tbl for sublist in clusters.values() for tbl in sublist}
ungrouped_tables = [tbl for tbl in tables if tbl not in grouped_tables]

for table in ungrouped_tables:
    fields = tables[table]
    label = f"<<TABLE BORDER='1' CELLBORDER='1' CELLSPACING='0'>"
    label += f"<TR><TD BGCOLOR='lightblue'><B>{table}</B></TD></TR>"
    for field in fields:
        label += f"<TR><TD ALIGN='LEFT'>{field}</TD></TR>"
    label += "</TABLE>>"
    dot.node(table, label=label, shape="plaintext")

# === Добавляем невидимые связи между кластерами (для горизонтального порядка)
dot.edge("city", "event", style="invis")
dot.edge("event", "user", style="invis")
dot.edge("user", "interest", style="invis")
dot.edge("interest", "announcement", style="invis")

# === Связи
for from_table, from_card, to_card, to_table, label in relations:
    style = 'dashed' if from_card == '?' or to_card == '?' else 'solid'
    needs_spread = from_table == 'user'

    dot.edge(from_table, to_table,
             xlabel=label,
             arrowhead='crow',
             dir='both',
             taillabel=from_card,
             headlabel=to_card,
             labeldistance='1.5',
             labelfontsize='10',
             fontsize='10',
             style=style,
             minlen='1',
             weight='2',
             constraint='false' if needs_spread else 'true')

# === Сохраняем PNG
dot.render(output_path, format='pdf', cleanup=True)
print("✅ Диаграмма сохранена как diagram_final.pdf")
