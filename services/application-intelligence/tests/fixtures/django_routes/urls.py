from django.urls import path, re_path

urlpatterns = [
    path('users/', get_users),
    path('items/<int:id>/', item_ops),
    re_path(r'^articles/(?P<year>[0-9]{4})/$', year_archive),
]
