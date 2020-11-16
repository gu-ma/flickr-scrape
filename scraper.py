from __future__ import print_function
import time
import sys
import json
import re
import os
import requests
from tqdm import tqdm
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta

with open('credentials.json') as infile:
    creds = json.load(infile)

KEY = creds['KEY']
SECRET = creds['SECRET']

def download_file(url, local_filename):
    if local_filename is None:
        local_filename = url.split('/')[-1]
    r = requests.get(url, stream=True)
    with open(local_filename, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)
    return local_filename


def get_group_id_from_url(url):
    params = {
        'method' : 'flickr.urls.lookupGroup',
        'url': url,
        'format': 'json',
        'api_key': KEY,
        'format': 'json',
        'nojsoncallback': 1
    }
    results = requests.get('https://api.flickr.com/services/rest', params=params).json()
    return results['group']['id']


def get_photos(qs, qg, page=1, original=False, bbox=None, from_date=None, to_date=None, results_per_page=500):
    params = {
        'content_type': '7',
        'per_page': results_per_page,
        'media': 'photos',
        'format': 'json',
        'advanced': 1,
        'nojsoncallback': 1,
        'extras': f"media,realname,{'url_o' if original else 'url_l'},o_dims,geo,tags,machine_tags,date_upload,date_taken", #url_c,url_l,url_m,url_n,url_q,url_s,url_sq,url_t,url_z',
        'page': page,
        'api_key': KEY
    }

    if from_date and to_date:
        params['min_upload_date'] = from_date,
        params['max_upload_date'] = to_date

    if qs:
        params['method'] = 'flickr.photos.search',
        params['text'] = qs

    if qg:
        if not qs:
            params['method'] = 'flickr.groups.pools.getPhotos'
        params['group_id'] = qg

    # bbox should be: minimum_longitude, minimum_latitude, maximum_longitude, maximum_latitude
    if bbox and len(bbox) == 4:
        params['bbox'] = ','.join(bbox)

    try:
        results = requests.get('https://api.flickr.com/services/rest', params=params).json()
    except Exception as e:
        print(e)

    if "photos" not in results:
        print(results)
        return None

    return results["photos"]


def get_range(from_date, to_date, max_results=4000):
    results_per_page = 500
    delta = to_date - from_date
    while True:
        results = get_photos(
            qs,
            qg,
            page=1,
            original=original,
            bbox=bbox,
            from_date=datetime.fromordinal(from_date.toordinal()).timestamp(),
            to_date=datetime.fromordinal(to_date.toordinal()).timestamp(),
            results_per_page=results_per_page
        )
        pages = int(results['pages'])
        total = int(results['total'])
        # print(f'{to_date}, {from_date}, {pages}, {total}')
        if pages * results_per_page > max_results:
            delta /= 4
            from_date = to_date - delta
        else:
            return from_date, to_date, pages, total, results_per_page


def search(qs, qg, qgn, bbox=None, original=False, count=None, from_date=None, to_date=None):

    # create a folder for the query if it does not exist
    foldername = os.path.join('images', re.sub(r'[\W]', '_', qgn), re.sub(r'[\W]', '_', qs))

    if bbox:
        foldername += '_'.join(bbox)

    if not os.path.exists(foldername):
        os.makedirs(foldername)

    jsonfilename = os.path.join(foldername, f'results{str(count) if count else 'all'}.json')

    if not os.path.exists(jsonfilename):

        photos = []
        to_date = date.today() if not to_date else to_date
        from_date = to_date - timedelta(365*20) if not from_date else from_date

        results = get_photos(
            qs,
            qg,
            original=original,
            bbox=bbox,
            from_date=from_date,
            to_date=to_date
        )
        if results is None:
            return

        total_results = int(results['total'])
        print(f'Found {total_results} results between {from_date} and {to_date}')
        count = total_results if not count else count

        # Split in date ranges to avoid the 4,000 results max limit
        # Slow, but hey, it works :P
        print('Spliting in date ranges\n---')
        total_results_in_range = 0
        dates_ranges = []
        while to_date > from_date and total_results_in_range < count:
            data = get_range(from_date, to_date)
            to_date = data[0]
            total_results_in_range += data[3]
            dates_ranges.append({
                'from': data[0],
                'to': data[1],
                'pages': data[2],
                'total': data[3],
                'results_per_page': data[4]
            })
            print(f"{data[1]} -> {data[0]}: {data[2]} pages and {data[3]} results")

        print(f"{total_results} result in total / {total_results_in_range} in data ranges / {count} count\n---")

        photos += results['photo']

        for r in dates_ranges:

            current_page = 1
            total_pages = r['pages']

            while current_page < total_pages:

                print(f"{r['to']} -> {r['from']}: downloading metadata, page {current_page} of {total_pages}")
                current_page += 1
                photos += get_photos(
                    qs,
                    qg,
                    page=current_page,
                    original=original,
                    bbox=bbox,
                    from_date=datetime.fromordinal(r['from'].toordinal()).timestamp(),
                    to_date=datetime.fromordinal(r['to'].toordinal()).timestamp(),
                    results_per_page=r['results_per_page']
                )['photo']

                time.sleep(0.5)

        # dates = [ photo['dateupload'] for photo in photos ]
        # print(f'{dates[:10]} - {date[-10:]}')

        # unique = set([ photo['id'] for photo in photos ])
        # print(f'{len(unique)}/{len(photos)} unique')

        photos = photos[:count]
        with open(jsonfilename, 'w') as outfile:
            json.dump(photos, outfile)

    else:
        with open(jsonfilename, 'r') as infile:
            photos = json.load(infile)

    url_size = 'url_o' if original else 'url_l'

    # Remove photos without url
    photos = [photo for photo in photos if url_size in photo.keys()]

    # download images
    print('Downloading images')
    for photo in tqdm(photos):
        try:
            url = photo.get(url_size)
            extension = url.split('.')[-1]
            localname = os.path.join(foldername, '{}.{}'.format(photo['id'], extension))
            if not os.path.exists(localname):
                download_file(url, localname)
        except Exception as e:
            print(photo['id'], e)
            continue


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Download images from flickr')
    parser.add_argument('--search', '-s', dest='q_search', default=None, required=False, help='Search term')
    parser.add_argument('--group', '-g', dest='q_group', default=None, required=False, help='Group url, e.g. https://www.flickr.com/groups/scenery/')
    parser.add_argument('--original', '-o', dest='original', action='store_true', default=False, required=False, help='Download original sized photos if True, large (1024px) otherwise')
    parser.add_argument('--from-date', '-fd', dest='from_date', required=False, help='From date yyyy-mm-dd (default today-20 years)')
    parser.add_argument('--to-date', '-td', dest='to_date', required=False, help='To date yyyy-mm-dd (default today)')
    parser.add_argument('--count', '-c', dest='count', default=0, required=False, help='Number of results')
    parser.add_argument('--bbox', '-b', dest='bbox', required=False, help='Bounding box to search in, separated by spaces like so: minimum_longitude minimum_latitude maximum_longitude maximum_latitude')
    args = parser.parse_args()

    qs = args.q_search if args.q_search else ''
    qg = args.q_group if args.q_group else ''
    qgn = args.q_group if args.q_group else ''
    original = args.original
    count = int(args.count)

    if not qs and not qg:
        sys.exit('Must specify a search term and / or group id')

    try:
        bbox = args.bbox.split(' ')
    except Exception as e:
        bbox = None

    if bbox and len(bbox) != 4:
        bbox = None

    if qg:
        qg = get_group_id_from_url(qg)

    print(f"Searching for '{qs}' in {args.q_group}")
    if bbox:
        print('Within', bbox)

    try:
        year, month, day = arg.to_date.split('-')
        to_date = date(year, month, day)
    except Exception as e:
        to_date = date.today()

    try:
        year, month, day = arg.from_date.split('-')
        from_date = date(year, month, day)
    except Exception as e:
        from_date = to_date - timedelta(365*20)

    search(qs, qg, qgn, bbox, original, count, from_date, to_date)

