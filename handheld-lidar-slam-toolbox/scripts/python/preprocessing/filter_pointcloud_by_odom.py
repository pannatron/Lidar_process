#!/usr/bin/env python3
import os
import sys
import time
import numpy as np
import scipy as sp
import argparse
from sklearn.decomposition import PCA

# Add the scripts/python directory to the Python path
script_dir = os.path.dirname(os.path.abspath(__file__))  # Get preprocessing dir
parent_dir = os.path.dirname(script_dir)  # Get python dir
sys.path.insert(0, parent_dir)

from core.pjfunc import readLas, readODM, writeLas
from core.convexhull import getInsidePoints2


def estimate_surface_normal(points):
    """
    Fit a plane to the ground points and get the normal vector.
    Uses RANSAC-like approach to get more robust normal estimation.
    
    Args:
        points: numpy array of shape (N, 3) containing point cloud data
    Returns:
        normal: normalized surface normal vector
        center: center point of ground points used for plane fitting
    """
    # First rough estimate of ground points
    z_min = np.percentile(points[:, 2], 2)  # Use bottom 2% as initial ground points
    ground_mask = points[:, 2] < z_min + 0.2  # Points within 20cm of lowest points
    ground_points = points[ground_mask]
    
    # If we have too many ground points, randomly sample them
    max_points = 10000  # Cap number of points for efficiency
    if len(ground_points) > max_points:
        indices = np.random.choice(len(ground_points), max_points, replace=False)
        ground_points = ground_points[indices]
    
    # Iterative refinement using RANSAC-like approach
    best_normal = None
    best_inliers = 0
    best_center = None
    
    for _ in range(10):  # Multiple iterations to find best fit
        # Randomly sample subset of points
        sample_size = min(1000, len(ground_points))
        sample_idx = np.random.choice(len(ground_points), sample_size, replace=False)
        sample_points = ground_points[sample_idx]
        
        # Fit plane using PCA
        pca = PCA(n_components=3)
        pca.fit(sample_points)
        
        # Get normal (third component is normal to plane)
        normal = pca.components_[2]
        center = np.mean(sample_points, axis=0)
        
        # Make sure normal points upward
        if normal[2] < 0:
            normal = -normal
            
        # Count inliers (points close to plane)
        vectors = ground_points - center
        distances = np.abs(np.dot(vectors, normal))
        inliers = np.sum(distances < 0.05)  # Points within 5cm of plane
        
        if inliers > best_inliers:
            best_normal = normal
            best_inliers = inliers
            best_center = center
    
    # Final refinement using all inlier points
    vectors = ground_points - best_center
    distances = np.abs(np.dot(vectors, best_normal))
    final_inliers = distances < 0.05
    final_points = ground_points[final_inliers]
    
    if len(final_points) > 0:
        pca = PCA(n_components=3)
        pca.fit(final_points)
        final_normal = pca.components_[2]
        if final_normal[2] < 0:
            final_normal = -final_normal
        final_center = np.mean(final_points, axis=0)
    else:
        final_normal = best_normal
        final_center = best_center
        
    return final_normal, final_center

def transform_to_normal_plane(points, normal, center):
    """
    Transform points to align with the normal plane.
    Uses more stable rotation computation.
    
    Args:
        points: nx3 array of points
        normal: normalized normal vector 
        center: point on the plane
    Returns:
        transformed_points: points in transformed space where normal is [0,0,1]
        rotation_matrix: the rotation matrix used
    """
    # Target is z-axis [0,0,1]
    z_axis = np.array([0, 0, 1])
    
    # Get rotation axis and angle
    rotation_axis = np.cross(normal, z_axis)
    if np.allclose(rotation_axis, 0):
        # Normal is already aligned with z-axis
        if normal[2] > 0:
            return points - center, np.eye(3)
        else:
            # Need 180° rotation around x-axis
            rotation_matrix = np.array([
                [1, 0, 0],
                [0, -1, 0],
                [0, 0, -1]
            ])
            return np.dot(points - center, rotation_matrix.T), rotation_matrix
            
    rotation_axis = rotation_axis / np.linalg.norm(rotation_axis)
    cos_theta = np.dot(normal, z_axis)
    sin_theta = np.sqrt(1 - cos_theta**2)
    
    # Build rotation matrix using improved Rodrigues formula
    K = np.array([[0, -rotation_axis[2], rotation_axis[1]],
                  [rotation_axis[2], 0, -rotation_axis[0]],
                  [-rotation_axis[1], rotation_axis[0], 0]])
    
    rotation_matrix = np.eye(3) + sin_theta * K + (1 - cos_theta) * np.dot(K, K)
    
    # Center and rotate points
    centered_points = points - center
    transformed_points = np.dot(centered_points, rotation_matrix.T)
    
    return transformed_points, rotation_matrix

def filter_by_height(points, min_height=None, max_height=None):
    """
    Filter points by height in transformed space where Z axis is aligned with normal.
    
    Args:
        points: nx3 array of points in transformed space
        min_height: minimum height to keep (optional)
        max_height: maximum height to keep (optional)
    Returns:
        mask: boolean array indicating which points to keep
    """
    mask = np.ones(len(points), dtype=bool)
    
    if min_height is not None:
        mask &= points[:, 2] >= min_height
    if max_height is not None:
        mask &= points[:, 2] <= max_height
        
    return mask

def process_with_normal_plane(data_path, odom_path, output_path=None, min_height=None, max_height=None, show_progress=False):
    """
    Process point cloud data by:
    1. Estimating surface normal from ground points
    2. Transforming points to align with normal plane 
    3. Filtering by height in transformed space
    4. Using 2D convex hull in transformed space
    5. Transforming points back to original space
    
    Args:
        data_path (str): Path to input LAS file
        odom_path (str): Path to odometry text file
        output_path (str, optional): Path to save output LAS file
        min_height (float, optional): Minimum height to keep after normal alignment
        max_height (float, optional): Maximum height to keep after normal alignment
        show_progress (bool): Whether to show progress messages
    
    Returns:
        tuple: (processed_data, bounds, normal_info)
    """
    t0 = time.time()
    
    # Check if files exist
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Data path {data_path} doesn't exist")
        
    if not os.path.exists(odom_path):
        raise FileNotFoundError(f"Odometry path {odom_path} doesn't exist")
    
    # Set default output path if none provided
    if output_path is None:
        base, ext = os.path.splitext(data_path)
        output_path = f"{base}_processed{ext}"
    
    # Read the data
    dat = readLas(data_path)
    x, y, z = readODM(odom_path)
    odm_points = np.column_stack((x, y, z))

    t1 = time.time()
    if show_progress:
        print(f"Finished data reading in {t1-t0:.3f} seconds")

    # Estimate surface normal
    normal, center = estimate_surface_normal(dat)
    if show_progress:
        print(f"Estimated surface normal: {normal}")
    
    # Transform points to align with normal plane
    transformed_data, rotation = transform_to_normal_plane(dat, normal, center)
    transformed_odm, _ = transform_to_normal_plane(odm_points, normal, center)  # Fixed variable name here
    
    # Filter by height in transformed space
    height_mask = filter_by_height(transformed_data, min_height, max_height)
    transformed_data = transformed_data[height_mask]
    dat = dat[height_mask]  # Also filter original points
    
    if show_progress and (min_height is not None or max_height is not None):
        print(f"Filtered points by height: kept {np.sum(height_mask)} of {len(height_mask)} points")
    
    # Perform convex hull in transformed space (now aligned with xy plane)
    hull_points = np.column_stack((transformed_odm[:,0], transformed_odm[:,1]))
    chull = sp.spatial.ConvexHull(hull_points)
    hull_vertices = hull_points[chull.vertices]
    
    # Filter points within convex hull in transformed space
    inside_points = getInsidePoints2(transformed_data[:,:2], hull_vertices)
    filtered_data = dat[inside_points]  # Use original points for output
    
    t2 = time.time()
    if show_progress:
        print(f"Finished normal-aligned filtering in {t2-t1:.3f} seconds")
        print(f"Total points after filtering: {len(filtered_data)}")

    # Save processed data
    writeLas(output_path, filtered_data)

    if show_progress:
        t3 = time.time()
        print(f"Finished file writing in {t3-t2:.3f} seconds")
        print(f"Total processing time: {t3-t0:.3f} seconds")

    # Calculate bounds
    bounds = {
        'xmin': np.floor(np.min(filtered_data[:,0])),
        'xmax': np.ceil(np.max(filtered_data[:,0])),
        'ymin': np.floor(np.min(filtered_data[:,1])),
        'ymax': np.ceil(np.max(filtered_data[:,1])),
        'zmin': np.floor(np.min(filtered_data[:,2])),
        'zmax': np.ceil(np.max(filtered_data[:,2]))
    }
    
    normal_info = {
        'normal': normal,
        'center': center,
        'rotation': rotation
    }
    
    return filtered_data, bounds, normal_info

def main():
    parser = argparse.ArgumentParser(
        description='Process point cloud by cutting along normal plane within convex hull'
    )
    parser.add_argument('las_file', help='Input LAS file path')
    parser.add_argument('odom_file', help='Input odometry text file path')
    parser.add_argument('-o', '--output', help='Output LAS file path (optional)')
    parser.add_argument('--min-height', type=float, help='Minimum height to keep after normal alignment')
    parser.add_argument('--max-height', type=float, help='Maximum height to keep after normal alignment')
    parser.add_argument('-p', '--progress', action='store_true', 
                       help='Show progress messages')
    
    args = parser.parse_args()
    
    try:
        data, bounds, normal_info = process_with_normal_plane(
            args.las_file,
            args.odom_file,
            args.output,
            args.min_height,
            args.max_height,
            args.progress
        )
        print(f"Successfully processed {args.las_file}")
        print("\nEstimated surface normal:", normal_info['normal'])
        print("Reference point:", normal_info['center'])
        print("\nData bounds:")
        for key, value in bounds.items():
            print(f"  {key}: {value}")
        print(f"Number of points in result: {len(data)}")
        
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        raise

if __name__ == '__main__':
    main()