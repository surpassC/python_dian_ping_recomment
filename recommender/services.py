from .algorithms.base import (
    PopularityRecommender,
    ContentBasedRecommender,
    CollaborativeRecommender,
    HybridRecommender
)
from .models import Restaurant, Rating
from django.db.models import Avg, Count, F, Func, Value, FloatField
from django.db.models.functions import Abs
from django.core.cache import cache
import numpy as np

class RecommenderService:
    def __init__(self):
        self.popularity_rec = PopularityRecommender()
        self.content_rec = ContentBasedRecommender()
        self.collab_rec = CollaborativeRecommender()
        self.hybrid_rec = HybridRecommender()

    def get_popular_restaurants(self, limit=4):
        """获取热门餐厅"""
        try:
            return Restaurant.objects.filter(
                review_count__gte=10
            ).exclude(
                name__iexact='nan'
            ).annotate(
                popularity_score=(F('avg_rating') * F('review_count'))
            ).order_by(
                '-popularity_score'
            )[:limit]
        except Exception as e:
            print(f"Error in get_popular_restaurants: {e}")
            return Restaurant.objects.none()

    def get_similar_restaurants(self, restaurant_id, limit=6):
        """获取相似餐厅"""
        return self.content_rec.recommend(restaurant_id=restaurant_id, n_recommendations=limit)

    def get_personalized_recommendations(self, user_id, limit=6):
        """获取个性化推荐"""
        return self.collab_rec.recommend(user_id=user_id, n_recommendations=limit)

    def get_hybrid_recommendations(self, user_id=None, restaurant_id=None, limit=6):
        """获取混合推荐"""
        return self.hybrid_rec.recommend(
            user_id=user_id,
            restaurant_id=restaurant_id,
            n_recommendations=limit
        )

    def get_top_rated_by_category(self, limit_per_category=5):
        """获取各评分维度的最佳餐厅"""
        return {
            'overall': Restaurant.objects.filter(review_count__gte=10).order_by('-avg_rating')[:limit_per_category],
            'flavor': Restaurant.objects.filter(review_count__gte=10).order_by('-avg_flavor_rating')[:limit_per_category],
            'environment': Restaurant.objects.filter(review_count__gte=10).order_by('-avg_env_rating')[:limit_per_category],
            'service': Restaurant.objects.filter(review_count__gte=10).order_by('-avg_service_rating')[:limit_per_category]
        }

    def get_similar_restaurants_fast(self, restaurant_id, limit=4):
        """快速获取相似餐厅"""
        try:
            # 1. 获取当前餐厅
            target = Restaurant.objects.get(rest_id=restaurant_id)
            
            # 2. 使用预计算的评分数据快速筛选
            similar_restaurants = Restaurant.objects.filter(
                review_count__gte=10  # 只考虑有足够评价的餐厅
            ).exclude(
                rest_id=restaurant_id
            ).exclude(
                name__iexact='nan'
            ).annotate(
                # 使用 Abs 函数计算差异
                rating_diff=Abs(F('avg_rating') - target.avg_rating),
                flavor_diff=Abs(F('avg_flavor_rating') - target.avg_flavor_rating),
                env_diff=Abs(F('avg_env_rating') - target.avg_env_rating),
                service_diff=Abs(F('avg_service_rating') - target.avg_service_rating)
            ).annotate(
                # 计算综合相似度得分
                similarity_score=Value(5.0, output_field=FloatField()) - (
                    F('rating_diff') + 
                    F('flavor_diff') + 
                    F('env_diff') + 
                    F('service_diff')
                ) / 4.0
            ).filter(
                similarity_score__gt=0
            ).order_by('-similarity_score', '-avg_rating')[:limit]
            
            return similar_restaurants
            
        except Restaurant.DoesNotExist:
            return Restaurant.objects.none()
        except Exception as e:
            print(f"Error in get_similar_restaurants_fast: {e}")
            return Restaurant.objects.none()
    
    def get_personalized_recommendations_fast(self, user_id, current_restaurant_id=None, limit=4):
        """快速获取个性化推荐"""
        try:
            # 1. 获取用户的评分历史
            user_ratings = Rating.objects.filter(user_id=user_id)
            
            if not user_ratings.exists():
                # 如果用户没有评分历史，返回热门餐厅
                return self.get_popular_restaurants(limit)
            
            # 2. 计算用户的口味偏好
            user_avg = user_ratings.aggregate(
                avg_rating=Avg('rating'),
                avg_flavor=Avg('rating_flavor'),
                avg_env=Avg('rating_env'),
                avg_service=Avg('rating_service')
            )
            
            # 3. 快速筛选符合用户偏好的餐厅
            recommendations = Restaurant.objects.filter(
                review_count__gte=10
            ).exclude(
                rest_id__in=user_ratings.values_list('restaurant_id', flat=True)
            ).exclude(
                name__iexact='nan'
            )
            
            if current_restaurant_id:
                recommendations = recommendations.exclude(rest_id=current_restaurant_id)
            
            recommendations = recommendations.annotate(
                rating_diff=Abs(F('avg_rating') - user_avg['avg_rating']),
                flavor_diff=Abs(F('avg_flavor_rating') - user_avg['avg_flavor']),
                env_diff=Abs(F('avg_env_rating') - user_avg['avg_env']),
                service_diff=Abs(F('avg_service_rating') - user_avg['avg_service'])
            ).annotate(
                match_score=Value(5.0, output_field=FloatField()) - (
                    F('rating_diff') + 
                    F('flavor_diff') + 
                    F('env_diff') + 
                    F('service_diff')
                ) / 4.0
            ).filter(
                match_score__gt=0
            ).order_by('-match_score', '-avg_rating')[:limit]
            
            return recommendations
            
        except Exception as e:
            print(f"Error in get_personalized_recommendations_fast: {e}")
            return Restaurant.objects.none()