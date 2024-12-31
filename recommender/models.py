from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import Avg

class Restaurant(models.Model):
    """餐厅模型"""
    rest_id = models.IntegerField(primary_key=True, verbose_name='餐厅ID', db_index=True)
    name = models.CharField(max_length=200, verbose_name='餐厅名称', db_index=True)
    dianping_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='大众点评ID')
    
    # 聚合评分字段（通过评分数据计算）
    avg_rating = models.FloatField(default=0, verbose_name='平均总评分', db_index=True)
    avg_flavor_rating = models.FloatField(default=0, verbose_name='平均口味评分')
    avg_env_rating = models.FloatField(default=0, verbose_name='平均环境评分')
    avg_service_rating = models.FloatField(default=0, verbose_name='平均服务评分')
    review_count = models.IntegerField(default=0, verbose_name='评论数量', db_index=True)

    class Meta:
        verbose_name = '餐厅'
        verbose_name_plural = '餐厅'
        indexes = [
            models.Index(fields=['avg_rating', 'review_count']),
            models.Index(fields=['avg_flavor_rating']),
            models.Index(fields=['avg_env_rating']),
            models.Index(fields=['avg_service_rating']),
        ]

    def __str__(self):
        return f"{self.name} (ID: {self.rest_id})"

    def update_ratings(self):
        """更新餐厅的评分统计"""
        ratings = self.ratings.all()
        if ratings:
            aggs = ratings.aggregate(
                avg_rating=Avg('rating'),
                avg_flavor=Avg('rating_flavor'),
                avg_env=Avg('rating_env'),
                avg_service=Avg('rating_service'),
                count=models.Count('id')
            )
            
            self.avg_rating = aggs['avg_rating'] or 0
            self.avg_flavor_rating = aggs['avg_flavor'] or 0
            self.avg_env_rating = aggs['avg_env'] or 0
            self.avg_service_rating = aggs['avg_service'] or 0
            self.review_count = aggs['count']
        else:
            self.avg_rating = 0
            self.avg_flavor_rating = 0
            self.avg_env_rating = 0
            self.avg_service_rating = 0
            self.review_count = 0
        
        self.save()

class Rating(models.Model):
    """评分模型"""
    user_id = models.IntegerField(verbose_name='用户ID', db_index=True)
    restaurant = models.ForeignKey(
        Restaurant, 
        on_delete=models.CASCADE, 
        related_name='ratings',
        verbose_name='餐厅'
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='总体评分'
    )
    rating_env = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='环境评分'
    )
    rating_flavor = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='口味评分'
    )
    rating_service = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name='服务评分'
    )
    timestamp = models.DateTimeField(verbose_name='评分时间')
    comment = models.TextField(blank=True, null=True, verbose_name='评论内容')

    class Meta:
        verbose_name = '评分'
        verbose_name_plural = '评分'
        unique_together = ('user_id', 'restaurant')
        indexes = [
            models.Index(fields=['user_id', 'restaurant']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"User {self.user_id} -> Restaurant {self.restaurant.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.restaurant.update_ratings()

class RestaurantLink(models.Model):
    """餐厅关联模型"""
    source = models.ForeignKey(
        Restaurant, 
        on_delete=models.CASCADE, 
        related_name='source_links',
        verbose_name='源餐厅'
    )
    target = models.ForeignKey(
        Restaurant, 
        on_delete=models.CASCADE, 
        related_name='target_links',
        verbose_name='目标餐厅'
    )
    weight = models.FloatField(default=0, verbose_name='关联权重')

    class Meta:
        verbose_name = '餐厅关联'
        verbose_name_plural = '餐厅关联'
        unique_together = ('source', 'target')

    def __str__(self):
        return f"{self.source.name} -> {self.target.name}"
