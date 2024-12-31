from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
from django.db import models, transaction
import pandas as pd
import numpy as np
from recommender.models import Restaurant, Rating
import os
from datetime import datetime
from tqdm import tqdm

class Command(BaseCommand):
    help = '从CSV文件导入餐厅数据'

    def handle(self, *args, **kwargs):
        # 文件路径
        restaurants_file = 'data/restaurants.csv'
        ratings_file = 'data/ratings.csv'
        links_file = 'data/links.csv'

        # 检查文件是否存在
        for file_path in [restaurants_file, ratings_file, links_file]:
            if not os.path.exists(file_path):
                self.stdout.write(self.style.ERROR(f'文件不存在: {file_path}'))
                return

        try:
            with transaction.atomic():
                # 清空现有数据
                self.stdout.write('清除现有数据...')
                Restaurant.objects.all().delete()
                Rating.objects.all().delete()

                # 1. 导入餐厅数据
                self.stdout.write('开始导入餐厅数据...')
                df_restaurants = pd.read_csv(restaurants_file)
                self.stdout.write(f'发现 {len(df_restaurants)} 条餐厅数据')
                
                restaurants = [
                    Restaurant(
                        rest_id=row['restId'],
                        name=row['name']
                    )
                    for _, row in df_restaurants.iterrows()
                ]
                Restaurant.objects.bulk_create(restaurants)
                self.stdout.write(f'成功导入 {len(restaurants)} 家餐厅')

                # 2. 导入评分数据
                self.stdout.write('开始导入评分数据...')
                # 读取时填充NaN值
                df_ratings = pd.read_csv(ratings_file)
                # 填充缺失值
                df_ratings = df_ratings.fillna({
                    'rating': 0,
                    'rating_env': 1,
                    'rating_flavor': 1,
                    'rating_service': 1,
                    'comment': ''
                })
                self.stdout.write(f'发现 {len(df_ratings)} 条评分数据')
                
                # 打印时间戳示例
                self.stdout.write(f'时间戳示例: {df_ratings["timestamp"].iloc[0]}')
                
                # 批量创建评分
                batch_size = 10000
                for i in tqdm(range(0, len(df_ratings), batch_size)):
                    batch = df_ratings.iloc[i:i+batch_size]
                    ratings = []
                    for _, row in batch.iterrows():
                        try:
                            # 处理时间戳
                            timestamp = make_aware(datetime.fromtimestamp(row['timestamp']/1000))  # 除以1000转换毫秒为秒
                            
                            # 确保评分值是有效的整数
                            rating = int(row['rating']) if not np.isnan(row['rating']) else 0
                            rating_env = int(row['rating_env']) if not np.isnan(row['rating_env']) else 1
                            rating_flavor = int(row['rating_flavor']) if not np.isnan(row['rating_flavor']) else 1
                            rating_service = int(row['rating_service']) if not np.isnan(row['rating_service']) else 1
                            
                            ratings.append(Rating(
                                user_id=row['userId'],
                                restaurant_id=row['restId'],
                                rating=rating,
                                rating_env=rating_env,
                                rating_flavor=rating_flavor,
                                rating_service=rating_service,
                                timestamp=timestamp,
                                comment=str(row.get('comment', ''))
                            ))
                        except Exception as e:
                            self.stdout.write(self.style.WARNING(f'处理评分数据时出错: {str(e)}, 行数据: {row.to_dict()}'))
                            continue
                    
                    if ratings:  # 只有当列表非空时才创建
                        Rating.objects.bulk_create(ratings)
                    self.stdout.write(f'已导入 {i + len(batch)} 条评分数据')

                # 3. 更新餐厅评分
                self.stdout.write('更新餐厅评分统计...')
                for restaurant in tqdm(Restaurant.objects.all()):
                    restaurant.update_ratings()

                # 4. 导入大众点评ID
                self.stdout.write('导入大众点评ID...')
                df_links = pd.read_csv(links_file)
                for _, row in df_links.iterrows():
                    Restaurant.objects.filter(rest_id=row['restId']).update(
                        dianping_id=row['dianpingId']
                    )

                # 打印统计信息
                restaurant_count = Restaurant.objects.count()
                rating_count = Rating.objects.count()
                rated_restaurant_count = Restaurant.objects.filter(review_count__gt=0).count()

                self.stdout.write(self.style.SUCCESS(
                    f'\n导入完成！\n'
                    f'餐厅总数: {restaurant_count}\n'
                    f'评分总数: {rating_count}\n'
                    f'有评分的餐厅数: {rated_restaurant_count}'
                ))

                # 打印一些示例数据
                self.stdout.write('\n示例餐厅数据:')
                for restaurant in Restaurant.objects.filter(review_count__gt=0)[:5]:
                    self.stdout.write(
                        f'\n餐厅: {restaurant.name} (ID: {restaurant.rest_id})\n'
                        f'  总评分: {restaurant.avg_rating:.2f}\n'
                        f'  评论数: {restaurant.review_count}\n'
                        f'  口味评分: {restaurant.avg_flavor_rating:.2f}\n'
                        f'  环境评分: {restaurant.avg_env_rating:.2f}\n'
                        f'  服务评分: {restaurant.avg_service_rating:.2f}'
                    )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'导入过程中出错: {str(e)}'))
            raise 