from django.urls import path

from module.employee.module.role.view.employees_roles_collection import EmployeesRolesCollection
from module.employee.module.role.view.employees_roles_detail import EmployeesRolesDetail

urlpatterns = [
    # the calling url.py in employee.url we determined that  the default usl for this module is api/employees/<role_name:int>/ so when you write "" as the first argument  it will be automatically replaced by api/employees/<role_name:int>/ and role/ is added at the end because the default path in employee.url for role module is "role/"
    path("", EmployeesRolesCollection.as_view()),
    path("<str:role_name>/", EmployeesRolesDetail.as_view()),
]