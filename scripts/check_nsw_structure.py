from nsw_fuel import FuelCheckClient

client = FuelCheckClient()
data = client.get_fuel_prices()

if data.prices:
    p = data.prices[0]
    print(f"Price object keys: {dir(p)}")
    print(f"Price: {p.price}")
    if hasattr(p, 'last_updated'):
        print(f"Last updated: {p.last_updated} (Type: {type(p.last_updated)})")
    else:
        print("No last_updated field found")
else:
    print("No prices found")
