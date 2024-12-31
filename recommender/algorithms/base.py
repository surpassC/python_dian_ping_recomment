from abc import ABC, abstractmethod
import numpy as np
from django.db.models import Avg, Count, F, ExpressionWrapper, FloatField, Q
from django.db.models.functions import Ln
from django.db import models
from ..models import Restaurant, Rating

class BaseRecommender(ABC):
    """推荐算法基类"""
    
    @abstractmethod
    def recommend(self, user_id=None, restaurant_id=None, n_recommendations=5):
        """推荐方法"""
        pass
    
    def get_user_ratings(self, user_id):
        """获取用户的评分记录"""
        return Rating.objects.filter(user_id=user_id)
    
    def get_restaurant_ratings(self, restaurant_id):
        """获取餐厅的评分记录"""
        return Rating.objects.filter(restaurant_id=restaurant_id)
    
    def calculate_similarity(self, vector1, vector2):
        """计算余弦相似度"""
        dot_product = np.dot(vector1, vector2)
        norm1 = np.linalg.norm(vector1)
        norm2 = np.linalg.norm(vector2)
        return dot_product / (norm1 * norm2) if norm1 and norm2 else 0

    def filter_valid_restaurants(self, queryset):
        """过滤有效的餐厅"""
        return queryset.exclude(
            Q(name__isnull=True) | 
            Q(name__exact='') | 
            Q(name__iexact='nan') |
            Q(name__iexact='null')
        ).filter(
            review_count__gt=0
        )

class PopularityRecommender(BaseRecommender):
    """基于流行度的推荐"""
    
    def recommend(self, user_id=None, restaurant_id=None, n_recommendations=5):
        # 计算综合得分：评分 * ln(1 + 评论数)
        restaurants = Restaurant.objects.annotate(
            log_reviews=ExpressionWrapper(
                Ln(1.0 + F('review_count')),
                output_field=FloatField()
            )
        ).annotate(
            popularity_score=ExpressionWrapper(
                F('avg_rating') * F('log_reviews'),
                output_field=FloatField()
            )
        )
        
        # 先过滤有效餐厅，再排序和切片
        restaurants = self.filter_valid_restaurants(restaurants)
        return restaurants.order_by('-popularity_score')[:n_recommendations]

class ContentBasedRecommender(BaseRecommender):
    """基于内容的推荐"""
    
    def recommend(self, user_id=None, restaurant_id=None, n_recommendations=5):
        if not restaurant_id:
            return Restaurant.objects.none()
            
        try:
            target_restaurant = Restaurant.objects.get(rest_id=restaurant_id)
        except Restaurant.DoesNotExist:
            return Restaurant.objects.none()
            
        # 获取用户对该餐厅的评分
        ratings = Rating.objects.filter(restaurant_id=restaurant_id)
        if not ratings.exists():
            return Restaurant.objects.none()
            
        # 计算平均评分特征向量
        avg_ratings = ratings.aggregate(
            avg_rating=Avg('rating'),
            avg_env=Avg('rating_env'),
            avg_flavor=Avg('rating_flavor'),
            avg_service=Avg('rating_service')
        )
        
        # 构建特征向量
        target_vector = np.array([
            avg_ratings['avg_rating'] or 0,
            avg_ratings['avg_env'] or 0,
            avg_ratings['avg_flavor'] or 0,
            avg_ratings['avg_service'] or 0
        ])
        
        # 获取有效的餐厅列表
        valid_restaurants = self.filter_valid_restaurants(
            Restaurant.objects.exclude(rest_id=restaurant_id)
        )
        
        # 计算相似度
        similar_restaurants = []
        for restaurant in valid_restaurants:
            r_ratings = Rating.objects.filter(restaurant_id=restaurant.rest_id)
            if not r_ratings.exists():
                continue
                
            r_avg_ratings = r_ratings.aggregate(
                avg_rating=Avg('rating'),
                avg_env=Avg('rating_env'),
                avg_flavor=Avg('rating_flavor'),
                avg_service=Avg('rating_service')
            )
            
            r_vector = np.array([
                r_avg_ratings['avg_rating'] or 0,
                r_avg_ratings['avg_env'] or 0,
                r_avg_ratings['avg_flavor'] or 0,
                r_avg_ratings['avg_service'] or 0
            ])
            
            similarity = self.calculate_similarity(target_vector, r_vector)
            similar_restaurants.append((restaurant, similarity))
        
        # 排序并返回最相似的餐厅
        similar_restaurants.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in similar_restaurants[:n_recommendations]]

class CollaborativeRecommender(BaseRecommender):
    """基于协同过滤的推荐"""
    
    def recommend(self, user_id=None, restaurant_id=None, n_recommendations=5):
        if not user_id:
            return Restaurant.objects.none()
            
        # 获取用户的评分记录
        user_ratings = Rating.objects.filter(user_id=user_id)
        if not user_ratings.exists():
            return Restaurant.objects.none()
            
        # 构建用户-餐厅评分矩阵
        user_restaurant_matrix = {}
        all_ratings = Rating.objects.all()
        for rating in all_ratings:
            if rating.user_id not in user_restaurant_matrix:
                user_restaurant_matrix[rating.user_id] = {}
            user_restaurant_matrix[rating.user_id][rating.restaurant_id] = rating.rating
            
        # 找到相似用户
        similar_users = []
        target_user_ratings = user_restaurant_matrix[user_id]
        
        for other_user, other_ratings in user_restaurant_matrix.items():
            if other_user == user_id:
                continue
                
            # 获取共同评分的餐厅
            common_restaurants = set(target_user_ratings.keys()) & set(other_ratings.keys())
            if not common_restaurants:
                continue
                
            # 构建评分向量
            vector1 = np.array([target_user_ratings[r] for r in common_restaurants])
            vector2 = np.array([other_ratings[r] for r in common_restaurants])
            
            similarity = self.calculate_similarity(vector1, vector2)
            similar_users.append((other_user, similarity))
            
        # 排序找出最相似的用户
        similar_users.sort(key=lambda x: x[1], reverse=True)
        similar_users = similar_users[:10]  # 取前10个相似用户
        
        # 基于相似用户的评分推荐餐厅
        restaurant_scores = {}
        for similar_user, similarity in similar_users:
            user_ratings = user_restaurant_matrix[similar_user]
            for restaurant_id, rating in user_ratings.items():
                if restaurant_id not in target_user_ratings:  # 只推荐用户没有评分过的餐厅
                    if restaurant_id not in restaurant_scores:
                        restaurant_scores[restaurant_id] = []
                    restaurant_scores[restaurant_id].append(rating * similarity)
                    
        # 计算加权平均评分
        restaurant_avg_scores = {
            r_id: np.mean(scores) 
            for r_id, scores in restaurant_scores.items()
        }
        
        # 排序并返回推荐结果
        recommended_restaurants = sorted(
            restaurant_avg_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:n_recommendations]
        
        # 获取并过滤有效餐厅
        valid_restaurants = self.filter_valid_restaurants(
            Restaurant.objects.filter(rest_id__in=[r[0] for r in recommended_restaurants])
        )
        
        # 保持原有排序
        restaurant_dict = {r.rest_id: r for r in valid_restaurants}
        return [restaurant_dict[r[0]] for r in recommended_restaurants if r[0] in restaurant_dict]

class HybridRecommender(BaseRecommender):
    """混合推荐算法"""
    
    def __init__(self):
        self.popularity_rec = PopularityRecommender()
        self.content_rec = ContentBasedRecommender()
        self.collab_rec = CollaborativeRecommender()
        
    def recommend(self, user_id=None, restaurant_id=None, n_recommendations=5):
        recommendations = []
        weights = {
            'popularity': 0.3,
            'content': 0.3,
            'collaborative': 0.4
        }
        
        # 获取各种推荐结果
        popularity_recs = self.popularity_rec.recommend(
            n_recommendations=n_recommendations
        )
        content_recs = self.content_rec.recommend(
            restaurant_id=restaurant_id,
            n_recommendations=n_recommendations
        ) if restaurant_id else []
        collab_recs = self.collab_rec.recommend(
            user_id=user_id,
            n_recommendations=n_recommendations
        ) if user_id else []
        
        # 合并推荐结果
        restaurant_scores = {}
        
        # 添加基于流行度的推荐
        for i, rest in enumerate(popularity_recs):
            score = weights['popularity'] * (1.0 - i/len(popularity_recs))
            restaurant_scores[rest.rest_id] = restaurant_scores.get(rest.rest_id, 0) + score
            
        # 添加基于内容的推荐
        for i, rest in enumerate(content_recs):
            score = weights['content'] * (1.0 - i/len(content_recs))
            restaurant_scores[rest.rest_id] = restaurant_scores.get(rest.rest_id, 0) + score
            
        # 添加协同过滤推荐
        for i, rest in enumerate(collab_recs):
            score = weights['collaborative'] * (1.0 - i/len(collab_recs))
            restaurant_scores[rest.rest_id] = restaurant_scores.get(rest.rest_id, 0) + score
            
        # 排序并返回最终推荐结果
        recommended_restaurants = sorted(
            restaurant_scores.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:n_recommendations]
        
        return Restaurant.objects.filter(
            rest_id__in=[r[0] for r in recommended_restaurants]
        ) 