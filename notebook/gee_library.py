
import os
import random
import datetime
import zipfile
import ee
import matplotlib.image as mpimg
import requests, StringIO
import tifffile as tiff



class ServerError(Exception):
    """
    This exception communicates that a request to Google's severs returned
    a bad response.
    """
    pass



def unzipURL(img_url, tmp_directory = None):
    """
    Downloads and unzips a file in a tmp directory.
    Returns the path where everything is unzipped.
    Returns None on error.
    """

    #
    # Set up temp directory
    #
    if tmp_directory == None:
        tmp_directory="./tmp/"+str(random.randrange(99999999))
    zip_filename = os.path.join(tmp_directory, 'zipped_tile.zip')
    # make tmp directory
    if not os.path.exists(tmp_directory):
        os.makedirs(tmp_directory)
    # and delete everything in it:
    filelist = [ f for f in os.listdir(tmp_directory)]
    for f in filelist:
        os.remove(os.path.join(tmp_directory, f))

    #
    # Download file
    #
    try:
        r = requests.get(img_url)
        sc = r.status_code
    except requests.ConnectionError as e:
        raise e

    if r.status_code == 200:
        z = zipfile.ZipFile(StringIO.StringIO(r.content))
        z.extractall(tmp_directory)
        z.close()
        return tmp_directory
    elif r.status_code == 400:
        print "Uh-oh. Status code 400 (Bad Request). Possible problems:"
        print "- You requested a band that wasn't available in every image."
        print "- Some other unknown issue."
        raise ServerError("Status code 400")
    elif r.status_code == 429:
        raise ServerError("Status code 429")
    else:
        raise ServerError("Uh-oh. Status code " + str(r.status_code))

    # Fall through on handled error/exception
    return None



def estimate_image_size_at_resolution(bounds_geometry, resolution):
    """
    Calculates the resulting image dimentions at a specific resolution.
    Right now this is very rough.

    bounds_geometry: actual geometry object
    """

    coords = bounds_geometry.getInfo()['coordinates'][0]


    xs = [x for [x,y] in coords]
    ys = [y for [x,y] in coords]

    top_left = min(xs), max(ys)
    bottom_left = min(xs), min(ys)
    bottom_right = max(xs), min(ys)

    height = ee.Geometry.Point(top_left).distance(ee.Geometry.Point(bottom_left)).getInfo() / resolution
    width = ee.Geometry.Point(bottom_left).distance(ee.Geometry.Point(bottom_right)).getInfo() / resolution

    return {
        'height': height,
        'width': width }



def img_at_region(geCollection, resolution, bands, geo_bounds, verbose=False):
    tif_band_dictionary = tif_at_region(geCollection, resolution, bands, geo_bounds, verbose)
    img_band_dictionary = {}

    for k,v in tif_band_dictionary.items():
        # img_band_dictionary[k] = mpimg.imread(v)
        img_band_dictionary[k] = tiff.imread(v)

    return img_band_dictionary


def tif_at_region(geCollection, resolution, bands, geo_bounds, verbose=False):
    """
    Converts a google earth engine Element object (an element of an Image Collection)
    into a numpy array that you can display.

    bands: ['10', '20', '30]

    Hits the server thrice.
        - Once for geo_bounds.getInfo()['coordinates']
        - Once for getDownloadUrl()
        - Once for downloading the zip
    """

    DEFAULT_MAP_NAME = 'map_section'

    # create the Google Earth Engine Image object
    gee_img = geCollection.filterBounds(geo_bounds).select(bands).mosaic()

    # convert the simple list of band names into the dictionary that the query needs
    bands_string = [{'id': b} for b in bands]

    # get the download link from google
    path=gee_img.getDownloadUrl({
            'name': DEFAULT_MAP_NAME,  # name the file (otherwise it will be a uninterpretable hash)
            'scale': resolution,                              # resolution in meters
            'crs': 'EPSG:4326', #4326                         #  projection
            'bands': bands_string,
            'region': geo_bounds.getInfo()['coordinates']
            });

    # debug output
    if verbose:
        print path

    # unzip the tiff
    tif_location = unzipURL(path)

    tif_filename_object = {}
    for b in bands:
        # each tif in the zip file is in the format 'mapname.band.tif'
        tif_filename = DEFAULT_MAP_NAME+'.'+b+'.tif'
        tif_path = os.path.join(tif_location, tif_filename)
        # add the calculated tif path to a dictionary, keyed by the band name
        tif_filename_object[b] = tif_path



    return tif_filename_object

def dates_available(geCollection):
    """
    Returns a list of the dates available for this collection.
    """

    timestamps =  geCollection.aggregate_array('system:time_start').getInfo()
    dateformat_array = [timestamp_to_datetime(t) for t in timestamps]

    return  dateformat_array


def available_bands(image_collection):
    """
    Returns a dictionary in format
    { "band1": { "number_available" : number of images that contain band1,
                 "percent_available" : percent of all images in collection that contain band1 }
                },
      "band2": {...
    }

    Hits the server 1+number_of_bands times
    """
    band_ids = [band_info['id']
                for band_info
                in image_collection.first().getInfo()['bands']]

    collection_size = image_collection.size().getInfo()

    availability_dict = {}
    for b in band_ids:
        imgs_available = image_collection.select(b).size().getInfo()
        percent_available = imgs_available/collection_size*100
        availability_dict[b] = {
            "number_available": imgs_available,
            "percent_available": percent_available
        }
        # print "'"+b+"' available in "+ str(imgs_available) + " images. ("+str(percent_available)+"%)"

    return availability_dict

def timestamp_to_datetime(timestamp, time_format = '%Y-%m-%d'):
    return datetime.datetime.fromtimestamp(timestamp/1000).strftime(time_format)


def date_range(image_collection):
    time_format = '%Y-%m-%d'
    min_time = image_collection.aggregate_min('system:time_start').getInfo()
    max_time = image_collection.aggregate_max('system:time_end').getInfo()

    return {
        'begin_time': datetime.datetime.fromtimestamp(min_time/1000).strftime(time_format),
        'end_time': datetime.datetime.fromtimestamp(max_time/1000).strftime(time_format)
    }

def collection_length(image_collection):
    return image_collection.size().getInfo()

def bound_geometry(corner1, corner2):
    """ Given 2 points, returns a Geometry object that represents the square
    those 2 points make up. """

    x1, y1 = corner1
    x2, y2 = corner2

    # How important is this? I don't know.
    left_x,top_y     = min([x1, x2]), max([y1, y2])
    right_x,bottom_y = max([x1, x2]), min([y1, y2])

    xMin=min([x1, x2])
    yMin=min([y1, y2])
    xMax=max([x1, x2])
    yMax=max([y1, y2])

    # First create a "linear ring" that is the outline of the points.
    rectangle_representation = ee.Geometry.Rectangle([xMin, yMin, xMax, yMax])

    # then fill in this ring by calculating the convex hull
    return rectangle_representation


def square_centered_at(point, half_distance):
    """
    Returns a ee.Geometry object that is a square, centered at `point`,
    where each side measures 2 times `half_distance`.

    `point`: (long, lat)
    `distance`: in meters

    Doesn't hit the server.
    """

    return ee.Geometry.Point(point).buffer(half_distance).bounds()
