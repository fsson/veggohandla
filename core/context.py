def nav(request):
    """Which tab in the navigation is active."""
    name = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    if name.startswith("recipe"):
        section = "recipes"
    elif name.startswith(("shopping", "extra", "set_retailer")):
        section = "shopping"
    elif name.startswith(("ingredient_list", "ingredient_detail", "ingredient_reset", "match_preview", "alias")):
        section = "ingredients"
    elif name.startswith(("products", "index")):
        section = "products"
    else:
        section = "planner"
    return {"nav_section": section}
