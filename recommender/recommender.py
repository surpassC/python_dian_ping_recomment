from django.db import models
from .models import Restaurant, RestaurantLink

class RestaurantRecommender:
    def get_popular_restaurants(self, limit=6):
        """获取热门餐厅 - 基于评分和评论数"""
        return Restaurant.objects.annotate(
            score=models.ExpressionWrapper(
                models.F('rating') * models.F('review_count'),
                output_field=models.FloatField()
            )
        ).order_by('-score')[:limit]

    def get_similar_restaurants(self, restaurant_id, limit=5):
        """基于预计算的相似度获取相似餐厅"""
        return RestaurantLink.objects.filter(
            source_id=restaurant_id
        ).select_related('target').order_by('-weight')[:limit]

    def get_cuisine_type_recommendations(self, cuisine_type, limit=6):
        """获取同类型最佳餐厅"""
        return Restaurant.objects.filter(
            cuisine_type=cuisine_type
        ).order_by('-rating', '-review_count')[:limit]

    def get_price_range_recommendations(self, price, limit=6):
        """获取相似价格区间的高评分餐厅"""
        price_range = (price * 0.8, price * 1.2)  # 价格区间±20%
        return Restaurant.objects.filter(
            avg_price__range=price_range,
            rating__gte=4.0  # 只推荐好评餐厅
        ).order_by('-rating')[:limit]

    def get_comprehensive_recommendations(self, restaurant_id, limit=6):
        """综合推荐 - 结合相似度和评分"""
        restaurant = Restaurant.objects.get(pk=restaurant_id)
        similar_restaurants = set(
            link.target_id for link in 
            RestaurantLink.objects.filter(source_id=restaurant_id)
            .order_by('-weight')[:20]  # 获取前20个相似餐厅
        )
        
        return Restaurant.objects.filter(
            models.Q(restaurant_id__in=similar_restaurants) |
            models.Q(cuisine_type=restaurant.cuisine_type)
        ).filter(
            avg_price__range=(
                restaurant.avg_price * 0.7,
                restaurant.avg_price * 1.3
            )
        ).exclude(
            restaurant_id=restaurant_id
        ).order_by('-rating')[:limit] 