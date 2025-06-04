from celery import Celery

# RabbitMQ Broker URL
# 如果您的 RabbitMQ 伺服器有不同的主機、端口或憑證，請相應修改
# 預設: amqp://guest:guest@localhost:5672//
RABBITMQ_BROKER_URL = 'amqp://guest:guest@localhost:5672//'

# 建立 Celery 應用實例
# 'backend_app' 是應用程式的名稱，您可以自訂
# 您也可以設定 result_backend 如果需要儲存任務結果，例如使用 Redis 或 RabbitMQ (via RPC)
celery_app = Celery(
    'backend_app',
    broker=RABBITMQ_BROKER_URL,
    # backend='rpc://', # 如果希望使用 RabbitMQ 作為結果後端 (可選)
    include=[]  # 在這裡列出包含您的任務的模組，例如 ['app.tasks']
)

# 可選的 Celery 配置
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],  # 可接受的內容類型
    result_serializer='json',
    timezone='UTC',  # 建議設定時區
    enable_utc=True,
)

# 如果您將任務定義在其他檔案 (例如 backend/app/tasks.py)，
# 可以在 celery_app.conf.imports 中指定，或者在 include 參數中。
# 例如:
# celery_app.conf.imports = ('app.tasks',)

if __name__ == '__main__':
    celery_app.start()
