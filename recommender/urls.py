from django.urls import path
from . import views

app_name = 'recommender'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('restaurant/<int:rest_id>/', views.RestaurantDetailView.as_view(), name='restaurant_detail'),
    
    # API endpoints
    path('api/restaurant/<int:rest_id>/ratings/', views.restaurant_ratings_api, name='restaurant_ratings_api'),
    path('api/restaurant/<int:rest_id>/similar/', views.similar_restaurants_api, name='similar_restaurants_api'),
    path('api/restaurant/<int:rest_id>/recommendations/', views.restaurant_recommendations_api, name='recommendations_api'),
] 