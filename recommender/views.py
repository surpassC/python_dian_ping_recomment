from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView
from django.db.models import Avg, Count, Prefetch, Q
from .models import Restaurant, RestaurantLink, Rating
from .services import RecommenderService
from django.core.cache import cache
from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth import login, logout
from django.contrib import messages
from .forms import LoginForm, RegisterForm
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.shortcuts import redirect
from datetime import datetime

def index(request):
    recommender = RestaurantRecommender()
    
    # 获取热门餐厅
    popular_restaurants = recommender.get_popular_restaurants(limit=6)
    
    # 获取高评分餐厅（评分>=4.5）
    high_rated = Restaurant.objects.filter(
        rating__gte=4.5
    ).order_by('-review_count')[:6]
    
    # 获取不同价位区间的最佳餐厅
    price_ranges = {
        '经济实惠': (0, 50),
        '中等价位': (50, 100),
        '高端餐厅': (100, 1000)
    }
    price_recommendations = {}
    for label, (min_price, max_price) in price_ranges.items():
        price_recommendations[label] = Restaurant.objects.filter(
            avg_price__range=(min_price, max_price)
        ).order_by('-rating')[:4]
    
    # 获取热门菜系
    top_cuisines = Restaurant.objects.values('cuisine_type').annotate(
        count=Count('cuisine_type')
    ).order_by('-count')[:5]
    
    cuisine_recommendations = {}
    for cuisine in top_cuisines:
        cuisine_type = cuisine['cuisine_type']
        cuisine_recommendations[cuisine_type] = recommender.get_cuisine_type_recommendations(
            cuisine_type, limit=3
        )
    
    context = {
        'popular_restaurants': popular_restaurants,
        'high_rated_restaurants': high_rated,
        'price_recommendations': price_recommendations,
        'cuisine_recommendations': cuisine_recommendations,
    }
    return render(request, 'recommender/index.html', context)

class HomeView(ListView):
    template_name = 'recommender/home.html'
    context_object_name = 'restaurants'
    
    def get_queryset(self):
        return Restaurant.objects.filter(
            review_count__gt=0,
            avg_rating__gt=0
        ).exclude(
            name__iexact='nan'
        ).order_by('-avg_rating')[:12]
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 获取当前季节
        month = datetime.now().month
        if month in [3, 4, 5]:
            season = '春'
            season_keywords = ['春笋', '春卷', '清淡', '养生']
        elif month in [6, 7, 8]:
            season = '夏'
            season_keywords = ['冷面', '凉菜', '冰品', '烧烤']
        elif month in [9, 10, 11]:
            season = '秋'
            season_keywords = ['螃蟹', '牛肉', '火锅', '秋葵']
        else:
            season = '冬'
            season_keywords = ['火锅', '暖锅', '羊肉', '炖汤']

        # 构建季节性查询条件
        season_query = Q()
        for keyword in season_keywords:
            season_query |= Q(name__icontains=keyword)

        # 获取季节推荐餐厅
        seasonal_restaurants = Restaurant.objects.filter(
            season_query,
            review_count__gt=0,
            avg_rating__gte=4.0  # 只推荐4分以上的餐厅
        ).exclude(
            name__iexact='nan'
        ).order_by('-avg_rating')[:6]

        # 如果季节性推荐不足6个，补充高评分餐厅
        if seasonal_restaurants.count() < 6:
            existing_ids = set(seasonal_restaurants.values_list('rest_id', flat=True))
            additional_restaurants = Restaurant.objects.filter(
                review_count__gt=0,
                avg_rating__gte=4.5
            ).exclude(
                rest_id__in=existing_ids
            ).exclude(
                name__iexact='nan'
            ).order_by('-avg_rating')[:6-seasonal_restaurants.count()]
            
            seasonal_restaurants = list(seasonal_restaurants) + list(additional_restaurants)

        # 添加季节信息到上下文
        context['current_season'] = season
        context['seasonal_restaurants'] = seasonal_restaurants
        context['season_keywords'] = season_keywords

        # 原有的其他上下文数据保持不变
        context['popular_restaurants'] = Restaurant.objects.filter(
            review_count__gt=0
        ).exclude(
            name__iexact='nan'
        ).order_by('-review_count')[:6]
        
        context['top_rated'] = {
            '综合评分最高': Restaurant.objects.filter(
                avg_rating__gt=0
            ).exclude(
                name__iexact='nan'
            ).order_by('-avg_rating')[:6],
            
            '口味最佳': Restaurant.objects.filter(
                avg_flavor_rating__gt=0
            ).exclude(
                name__iexact='nan'
            ).order_by('-avg_flavor_rating')[:6],
            
            '环境优雅': Restaurant.objects.filter(
                avg_env_rating__gt=0
            ).exclude(
                name__iexact='nan'
            ).order_by('-avg_env_rating')[:6],
            
            '服务贴心': Restaurant.objects.filter(
                avg_service_rating__gt=0
            ).exclude(
                name__iexact='nan'
            ).order_by('-avg_service_rating')[:6]
        }
        
        if self.request.user.is_authenticated:
            service = RecommenderService()
            context['personalized_recommendations'] = service.get_personalized_recommendations_fast(
                user_id=self.request.user.id,
                limit=6
            )
        
        return context

class RestaurantDetailView(DetailView):
    model = Restaurant
    template_name = 'recommender/restaurant_detail.html'
    context_object_name = 'restaurant'
    pk_url_kwarg = 'rest_id'
    
    def get_object(self, queryset=None):
        rest_id = self.kwargs.get(self.pk_url_kwarg)
        # 尝试从缓存获取餐厅基本信息
        cache_key = f'restaurant_basic_{rest_id}'
        restaurant = cache.get(cache_key)
        
        if not restaurant:
            restaurant = get_object_or_404(Restaurant, rest_id=rest_id)
            # 缓存1小时
            cache.set(cache_key, restaurant, 3600)
        
        return restaurant
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rest_id = self.object.rest_id
        
        # 1. 获取最新评价（使用缓存）
        cache_key = f'restaurant_ratings_{rest_id}'
        ratings = cache.get(cache_key)
        if ratings is None:
            ratings = list(Rating.objects.filter(
                restaurant_id=rest_id
            ).select_related().order_by(
                '-timestamp'
            )[:5])  # 只显示最新5条评价
            cache.set(cache_key, ratings, 1800)  # 缓存30分钟
        context['ratings'] = ratings
        
        # 2. 获取相似餐厅（使用缓存）
        cache_key = f'similar_restaurants_{rest_id}'
        similar_restaurants = cache.get(cache_key)
        if similar_restaurants is None:
            service = RecommenderService()
            similar_restaurants = service.get_similar_restaurants_fast(
                restaurant_id=rest_id,
                limit=4  # 减少推荐数量
            )
            cache.set(cache_key, similar_restaurants, 3600)  # 缓存1小时
        context['similar_restaurants'] = similar_restaurants
        
        # 3. 获取个性化推荐（使用缓存）
        if self.request.user.is_authenticated:
            user_id = self.request.user.id
            cache_key = f'user_recommendations_{user_id}_{rest_id}'
            recommended_restaurants = cache.get(cache_key)
            if recommended_restaurants is None:
                service = RecommenderService()
                recommended_restaurants = service.get_personalized_recommendations_fast(
                    user_id=user_id,
                    current_restaurant_id=rest_id,
                    limit=4  # 减少推荐数量
                )
                cache.set(cache_key, recommended_restaurants, 1800)  # 缓存30分钟
            context['recommended_restaurants'] = recommended_restaurants
        
        return context

@require_http_methods(["GET"])
def restaurant_ratings_api(request, rest_id):
    try:
        # 限制查询数量并只选择需要的字段
        ratings = Rating.objects.filter(restaurant_id=rest_id).only(
            'user_id', 'rating', 'rating_flavor', 
            'rating_env', 'rating_service', 
            'comment', 'timestamp'
        ).order_by('-timestamp')[:10]  # 减少到10条评价
        
        data = {
            'ratings': [{
                'user_id': rating.user_id,
                'rating': rating.rating,
                'rating_flavor': rating.rating_flavor,
                'rating_env': rating.rating_env,
                'rating_service': rating.rating_service,
                'comment': rating.comment,
                'timestamp': rating.timestamp.strftime('%Y-%m-%d %H:%M')
            } for rating in ratings]
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def similar_restaurants_api(request, rest_id):
    try:
        # 简化相似餐厅的获取逻辑
        restaurants = Restaurant.objects.filter(
            review_count__gt=0
        ).exclude(
            rest_id=rest_id
        ).exclude(
            name__iexact='nan'
        ).order_by('-avg_rating')[:6]  # 简单地获取评分最高的6家餐厅
        
        data = {
            'restaurants': [{
                'rest_id': r.rest_id,
                'name': r.name,
                'avg_rating': r.avg_rating
            } for r in restaurants]
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_http_methods(["GET"])
def restaurant_recommendations_api(request, rest_id):
    try:
        # 简化推荐逻辑
        restaurants = Restaurant.objects.filter(
            review_count__gt=0
        ).exclude(
            rest_id=rest_id
        ).exclude(
            name__iexact='nan'
        ).order_by('?')[:6]  # 随机获取6家餐厅
        
        data = {
            'restaurants': [{
                'rest_id': r.rest_id,
                'name': r.name,
                'avg_rating': r.avg_rating
            } for r in restaurants]
        }
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

class CustomLoginView(LoginView):
    form_class = LoginForm
    template_name = 'recommender/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return reverse_lazy('recommender:home')
    
    def form_invalid(self, form):
        messages.error(self.request, '用户名或密码错误')
        return super().form_invalid(form)

def register_view(request):
    if request.user.is_authenticated:
        return redirect('recommender:home')
        
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, '注册成功！')
            return redirect('recommender:home')
        else:
            messages.error(request, '注册失败，请检查输入信息')
    else:
        form = RegisterForm()
    return render(request, 'recommender/register.html', {'form': form})

@require_http_methods(["GET", "POST"])  
def logout_view(request):
    logout(request)
    messages.success(request, '已成功退出登录')
    return redirect('recommender:home')

