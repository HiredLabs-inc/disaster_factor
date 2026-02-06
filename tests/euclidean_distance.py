import math as m

def calculate_euclidean_distance(p: tuple, q: tuple):
    return abs(m.sqrt(((p[0] - q[0])**2) + ((p[1]-q[1])**2)))

cities = [
        {
            'name': 'San Jose',
            'coord': (37.3387, -121.8853),
            },
        {
            'name': 'San Francisco',
            'coord': (37.78, -122.42),
            },
        {
            'name': 'South San Francisco',
            'coord': (37.647, -122.4077),
            },
        {
            'name': 'Los Angeles',
            'coord': (34.0549, -118.2426),
            },
        {
            'name': 'Monterey',
            'coord': (36.5973, -121.8978),
            },
        {
            'name': 'Napa',
            'coord': (38.2975, -122.2869),
            },
        {
            'name': 'Redding',
            'coord': (40.5754, -122.3836),
            },
        {
            'name': 'Sacramento',
            'coord': (38.5781, -121.4944),
            },
        {
            'name': 'Reno',
            'coord': (39.5299, -119.8143),
            },
        {
            'name': 'Concord',
            'coord': (37.9817, -122.0259),
            },
        {
            'name': 'Fairfield',
            'coord': (38.2492, -122.0405)
            },
        {
            'name': 'Dixon',
            'coord': (38.4455, -121.8233)
            },
        {
            'name': 'Davis',
            'coord': (38.5449, -121.7405)
            }
        ]

e = (37.99, -122.35)

e_distances = []

for c in cities:
    d = calculate_euclidean_distance(e, c['coord'])
    c['d'] = d
    e_distances.append(c)

sd = sorted(e_distances, key=lambda city: city['d'])

t1 = 'Euclidean Distance'
spacer = '*' * (25 - len(t1))

print(f'{spacer} {t1} {spacer}')

for city in sd:
    multiplier = int(4 + (city['d'] * 10))
    s = "-" * multiplier + ">"
    ns = ' ' * (80 - multiplier)
    print(f'Richmond{s}{ns}{city["name"]} ({city["d"]:.2f})')

