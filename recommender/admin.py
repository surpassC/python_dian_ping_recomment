from django.contrib import admin
from .models import Restaurant, Rating, RestaurantLink

@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ('rest_id', 'name', 'avg_rating', 'review_count', 'avg_flavor_rating', 'avg_env_rating', 'avg_service_rating')
    search_fields = ('name',)
    list_filter = ('avg_rating',)

@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'restaurant', 'rating', 'rating_flavor', 'rating_env', 'rating_service', 'timestamp')
    search_fields = ('restaurant__name', 'comment')
    list_filter = ('rating', 'rating_flavor', 'rating_env', 'rating_service')

@admin.register(RestaurantLink)
class RestaurantLinkAdmin(admin.ModelAdmin):
    list_display = ('source', 'target', 'weight')
    search_fields = ('source__name', 'target__name')
