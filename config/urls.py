from django.urls import include, path

urlpatterns = [
    path("api/employees/", include("module.employee.urls")),
]
