"""Маршруты приложения dashboard."""
from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic.base import RedirectView

from . import api, views

urlpatterns = [
    # Страницы
    path('', RedirectView.as_view(pattern_name='reports', permanent=False), name='root'),
    path('stats/', views.home, name='home'),
    path('login/', auth_views.LoginView.as_view(
        template_name='dashboard/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('shops/', views.shop_list, name='shops'),
    path('shops/<int:pk>/', views.shop_detail, name='shop_detail'),
    path('lines/', views.line_list, name='lines'),
    path('lines/<int:pk>/', views.line_detail, name='line_detail'),
    path('lines/<int:pk>/switch/', views.line_switch_product, name='line_switch'),

    # Отчёты (Смена/Сутки/Месяц/Квартал/Год/Период)
    path('reports/', views.reports_page, name='reports'),
    path('reports/build/', views.reports_build, name='reports_build'),
    path('reports/export/', views.reports_export, name='reports_export'),
    path('reports/export-multi/', views.reports_export_multi, name='reports_export_multi'),
    path('reports/source/toggle/', views.reports_toggle_source, name='reports_toggle_source'),

    # Логотип проекта (файл logo.svg / logo.png в корне)
    path('logo.svg', views.site_logo, name='site_logo'),

    # Продукция
    path('products/', views.products_list, name='products'),
    path('products/add/', views.product_add, name='product_add'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/edit/modal/', views.product_edit_modal, name='product_edit_modal'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),

    # Отчёт о простоях
    path('downtime/', views.downtime_page, name='downtime'),
    path('downtime/export/', views.downtime_export, name='downtime_export'),

    # API
    path('api/v1/counter/', api.CounterView.as_view(), name='api-counter'),
    path('api/v1/lines/<int:pk>/chart/', api.LineChartView.as_view(), name='api-chart'),
    path('api/v1/events/', api.EventsView.as_view(), name='api-events'),
    path('api/v1/downtime/chart/', api.DowntimeChartView.as_view(), name='api-downtime-chart'),
    path('api/v1/sim/lines/', api.SimLinesView.as_view(), name='api-sim-lines'),
    path('api/v1/sim/products/', api.SimProductsView.as_view(), name='api-sim-products'),
    path('api/v1/health/', api.HealthView.as_view(), name='api-health'),
]