from django.urls import path

from core import views as v

urlpatterns = [
    path("", v.home, name="home"),
    # Recipes
    path("recept/", v.recipe_list, name="recipe_list"),
    path("recept/ny/", v.recipe_create, name="recipe_create"),
    path("recept/importera/", v.recipe_import, name="recipe_import"),
    path("recept/tolka/", v.ingredient_preview, name="ingredient_preview"),
    path("recept/<int:pk>/", v.recipe_detail, name="recipe_detail"),
    path("recept/<int:pk>/redigera/", v.recipe_edit, name="recipe_edit"),
    path("recept/<int:pk>/radera/", v.recipe_delete, name="recipe_delete"),
    path("recept/<int:pk>/planera/", v.recipe_plan, name="recipe_plan"),
    # Week planner
    path("vecka/", v.planner, name="planner_current"),
    path("vecka/<str:week>/", v.planner, name="planner"),
    path("vecka/<str:week>/kopiera/", v.week_copy_previous, name="week_copy"),
    path("vecka/<str:week>/tom/", v.week_clear, name="week_clear"),
    path("vecka/<str:week>/sammanfattning/", v.week_summary, name="week_summary"),
    path("vecka/dag/<str:date>/", v.day_partial, name="day_partial"),
    path("maltid/valj/", v.recipe_picker, name="recipe_picker"),
    path("maltid/ny/", v.meal_add, name="meal_add"),
    path("maltid/flytta/", v.meal_move, name="meal_move"),
    path("maltid/<int:pk>/portioner/", v.meal_servings, name="meal_servings"),
    path("maltid/<int:pk>/ta-bort/", v.meal_delete, name="meal_delete"),
    # Shopping list
    path("handla/", v.shopping_list, name="shopping_current"),
    path("handla/butik/", v.set_retailer, name="set_retailer"),
    path("handla/extra/<int:pk>/", v.extra_item, name="extra_item"),
    path("handla/<str:week>/", v.shopping_list, name="shopping"),
    path("handla/<str:week>/rad/<int:ingredient_id>/", v.shopping_item, name="shopping_item"),
    path("handla/<str:week>/rad/<int:ingredient_id>/vara/", v.shopping_choose, name="shopping_choose"),
    path("handla/<str:week>/extra/sok/", v.extra_search, name="extra_search"),
    path("handla/<str:week>/extra/", v.extra_add, name="extra_add"),
    # Range (sortiment)
    path("sortiment/", v.products_view, name="products"),
    path("sortiment/status/", v.index_status, name="index_status"),
    path("sortiment/uppdatera/", v.index_start, name="index_start"),
]
