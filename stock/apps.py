import os
import sys
import threading
import time

from django.apps import AppConfig


class StockConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stock'

    def ready(self):
        # Planificateur local (runserver, processus enfant du reloader uniquement)
        if 'runserver' not in sys.argv:
            return
        if os.environ.get('RUN_MAIN') != 'true':
            return
        if os.environ.get('DISABLE_STOCK_ALERT_SCHEDULER') == '1':
            return

        def _loop():
            while True:
                try:
                    from stock.stock_alerts import process_stock_alert_schedule
                    process_stock_alert_schedule()
                except Exception:
                    pass
                time.sleep(300)  # vérifie toutes les 5 minutes

        t = threading.Thread(target=_loop, daemon=True, name='stock-alert-scheduler')
        t.start()
