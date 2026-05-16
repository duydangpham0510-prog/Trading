"""
Management command để chạy sync với FULL mode (fast_mode=False)
"""
from django.core.management.base import BaseCommand
from dashboard.sync_service import sync_market_data


class Command(BaseCommand):
    help = 'Chạy sync FULL với đầy đủ F-Score và Profit Growth (fast_mode=False)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('🔄 Bắt đầu FULL SYNC...'))
        self.stdout.write(self.style.WARNING('   - fast_mode=False'))
        self.stdout.write(self.style.WARNING('   - F-Score đầy đủ (9 bước Piotroski)'))
        self.stdout.write(self.style.WARNING('   - Profit Growth: YoY/QoQ/TTM'))
        self.stdout.write(self.style.WARNING('   - Industry & Foreign data\n'))

        result = sync_market_data(mode="full", fast_mode=False)

        self.stdout.write(self.style.SUCCESS(f'\n✅ Hoàn thành!'))
        self.stdout.write(f'   - Đã xử lý: {result.get("count", 0)} mã'))
        self.stdout.write(f'   - Thất bại: {len(result.get("failed", []))} mã')
