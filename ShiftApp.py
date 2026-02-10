import sys
import os
import csv
from datetime import datetime, timedelta
from PyQt5.QtWidgets import QAction, QApplication, QMainWindow, QFileDialog, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog, QMessageBox, QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QCheckBox, QPushButton
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QProgressDialog
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QIcon
import folium


def get_exif(filename):
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    image = Image.open(filename)
    exif_data = {}
    if hasattr(image, '_getexif'):
        exif = image._getexif()
        if exif is not None:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == "GPSInfo":
                    gps_data = {}
                    for gps_tag in value:
                        sub_tag = GPSTAGS.get(gps_tag, gps_tag)
                        gps_data[sub_tag] = value[gps_tag]
                    exif_data[tag] = gps_data
                else:
                    exif_data[tag] = value
    return exif_data, image.filename

def analyze_images(folder_path, min_time_diff):
    image_data = []
    for root, dirs, files in os.walk(folder_path):
        for filename in files:
            if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                full_path = os.path.join(root, filename)
                try:
                    exif_data, full_filename = get_exif(full_path)
                    date, time = exif_data.get('DateTimeOriginal', ' ').split()
                    gps_info = exif_data.get('GPSInfo', {})
                    latitude = gps_info.get('GPSLatitude', (0, 0, 0))
                    longitude = gps_info.get('GPSLongitude', (0, 0, 0))
                    altitude = gps_info.get('GPSAltitude', 0)
                    image_data.append([full_filename, latitude, longitude, altitude, date, time])
                except Exception as e:
                    print(f"Error processing {full_path}: {e}")

    image_data.sort(key=lambda x: datetime.strptime(x[4] + ' ' + x[5], '%Y:%m:%d %H:%M:%S'))
    sets = []
    current_set = []
    last_time = None

    for data in image_data:
        current_time = datetime.strptime(data[4] + ' ' + data[5], '%Y:%m:%d %H:%M:%S')
        if last_time is None or (current_time - last_time) <= timedelta(minutes=min_time_diff):
            current_set.append(data)
        else:
            sets.append(current_set)
            current_set = [data]
        last_time = current_time
    if current_set:
        sets.append(current_set)

    return sets

def dms_to_decimal(d, m, s):
    """Convert degrees, minutes, seconds to decimal."""
    return d + m / 60.0 + s / 3600.0

def format_coords(coord_tuple):
    """Format coordinates from tuple to string with degrees, minutes, and seconds."""
    degrees, minutes, seconds = coord_tuple
    return f"{degrees:.0f}° {minutes:.0f}' {seconds:.2f}\""

class CorrectionDialog(QDialog):
    def __init__(self, current_lat=0.0, current_lon=0.0, current_alt=0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correction for Latitude, Longitude, and Altitude")
        self.layout = QFormLayout(self)

        # Initialize line edits with current correction values
        self.lat_input = QLineEdit(str(current_lat), self)
        self.lon_input = QLineEdit(str(current_lon), self)
        self.alt_input = QLineEdit(str(current_alt), self)

        self.layout.addRow("Latitude Shift (decimal degrees):", self.lat_input)
        self.layout.addRow("Longitude Shift (decimal degrees):", self.lon_input)
        self.layout.addRow("Altitude Shift (meters):", self.alt_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.layout.addRow(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def get_corrections(self):
        return (float(self.lat_input.text()), float(self.lon_input.text()), float(self.alt_input.text()))

class ExportSelectionDialog(QDialog):
    def __init__(self, sets, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Sets to Export")
        self.layout = QVBoxLayout(self)

        self.checkbox_list = []
        for i, set in enumerate(sets):
            chk = QCheckBox(f"Set {i + 1} - {len(set)} Images", self)
            chk.setChecked(True)  # Default to checked
            self.layout.addWidget(chk)
            self.checkbox_list.append(chk)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def get_selected_indices(self):
        return [i for i, chk in enumerate(self.checkbox_list) if chk.isChecked()]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.min_time_diff = 20  # Default value
        self.folder_path = None
        self.image_sets = None
        self.corrections = []
        self.ppk_data = []  # Store PPK data
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Shift App')
        self.setGeometry(300, 300, 600, 400)
        self.createMenus()
        icon = QIcon(r'D:\Codes\Shift-App\UAV-Icon.png')
        self.setWindowIcon(icon)

        layout = QVBoxLayout()
        self.tableWidget = QTableWidget()
        self.tableWidget.setColumnCount(7)
        self.tableWidget.setHorizontalHeaderLabels(['Set', 'Start Time', 'End Time', 'Number of Images', 'Delta Latitude', 'Delta Longitude', 'Delta Altitude'])
        self.tableWidget.doubleClicked.connect(self.table_double_clicked)
        widget = QWidget()
        widget.setLayout(layout)
        layout.addWidget(self.tableWidget)
        self.setCentralWidget(widget)

        # Create the clear button
        clear_button = QPushButton("Clear Data")
        clear_button.clicked.connect(self.clear_data)  # Connect button click to clear_data method

        widget = QWidget()
        widget.setLayout(layout)
        layout.addWidget(self.tableWidget)
        layout.addWidget(clear_button)  # Add the clear button to the layout
        self.setCentralWidget(widget)

    def createMenus(self):
        menubar = self.menuBar()

        # File Menu
        fileMenu = menubar.addMenu('File')
        importAction = QAction('Import Directory', self)
        importAction.triggered.connect(self.loadFolder)
        fileMenu.addAction(importAction)

        importcorrections = QAction('Import Transforms', self)
        importcorrections.triggered.connect(self.loadcorrections)
        fileMenu.addAction(importcorrections)

        importppkfile = QAction('Import PPK Path', self)
        importppkfile.triggered.connect(self.loadppkpath)
        fileMenu.addAction(importppkfile)

        # Processing Menu
        processingMenu = menubar.addMenu('Processing')
        setTimeDiffAction = QAction('Set Time Difference', self)
        setTimeDiffAction.triggered.connect(self.setTimeDifference)
        processingMenu.addAction(setTimeDiffAction)

        exportAction = QAction('Export Sets', self)
        exportAction.triggered.connect(self.export_all_sets)
        processingMenu.addAction(exportAction)

        updatecoorppk = QAction('PPK Process', self)
        updatecoorppk.triggered.connect(self.ppkprocess)
        processingMenu.addAction(updatecoorppk)

        # View Menu
        viewMenu = menubar.addMenu('Map')
        viewonmap = QAction('View on Map', self)
        viewonmap.triggered.connect(self.showmap)
        viewMenu.addAction(viewonmap)

    def setTimeDifference(self):
        min_time_diff, ok = QInputDialog.getInt(self, "Set Time Difference", "Enter the minimum time difference between sets (in minutes):", min=1, max=120, step=1, value=self.min_time_diff)
        if ok:
            self.min_time_diff = min_time_diff

    def loadFolder(self):
        self.folder_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if self.folder_path:
            self.image_sets = analyze_images(self.folder_path, self.min_time_diff)
            self.tableWidget.setRowCount(len(self.image_sets))
            for i, imageset in enumerate(self.image_sets):
                start_time = datetime.strptime(imageset[0][4] + ' ' + imageset[0][5], '%Y:%m:%d %H:%M:%S')
                end_time = datetime.strptime(imageset[-1][4] + ' ' + imageset[-1][5], '%Y:%m:%d %H:%M:%S')
                self.tableWidget.setItem(i, 0, QTableWidgetItem(str(i + 1)))
                self.tableWidget.setItem(i, 1, QTableWidgetItem(start_time.strftime('%Y-%m-%d %H:%M:%S')))
                self.tableWidget.setItem(i, 2, QTableWidgetItem(end_time.strftime('%Y-%m-%d %H:%M:%S')))
                self.tableWidget.setItem(i, 3, QTableWidgetItem(str(len(imageset))))
                self.tableWidget.setItem(i, 4, QTableWidgetItem("0.000000"))
                self.tableWidget.setItem(i, 5, QTableWidgetItem("0.000000"))
                self.tableWidget.setItem(i, 6, QTableWidgetItem("0.00"))

    def loadcorrections(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open CSV", "", "CSV Files (*.csv)")
        if filename:
            try:
                with open(filename, newline='') as file:
                    reader = csv.DictReader(file)
                    self.corrections = list(reader)
                self.apply_corrections()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load corrections: {e}")
    
    def loadppkpath(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open PPK File", "", "CSV Files (*.csv)")
        if filename:
            try:
                self.ppk_data.clear()
                with open(filename, newline='') as file:
                    reader = csv.DictReader(file)
                    for row in reader:
                        date, time = row['Date/Time'].split()
                        lat = float(row['WGS84 Latitude'])
                        lon = float(row['WGS84 Longitude'])
                        alt = float(row['WGS84 Ellip. Height'])
                        self.ppk_data.append((date, time, lat, lon, alt))
                QMessageBox.information(self, "Success", "PPK data loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load PPK data: {e}")
    
    def clear_data(self):
        self.tableWidget.setRowCount(0)  # Clear all rows from the table
        self.image_sets = []  # Reset the image sets
        self.ppk_data = []  # Reset the PPK data
        self.corrections = []  # Reset the corrections
        QMessageBox.information(self, "Cleared", "All data has been cleared.")


    def ppkprocess(self):
        if not self.image_sets or not self.ppk_data:
            QMessageBox.warning(self, "Missing Data", "Ensure both image sets and PPK data are loaded.")
            return

        # Flatten the image sets into a single list for easier processing
        all_images = [img for imageset in self.image_sets for img in imageset]

        # Normalize and parse the image times and PPK times
        def normalize_date(date_str):
            """Normalize date by removing leading zeros and converting to a consistent format."""
            return date_str.replace('-', '/').replace(':', '/').lstrip('0')

        image_times = [datetime.strptime(normalize_date(img[4]) + ' ' + img[5], '%Y/%m/%d %H:%M:%S') for img in all_images]
        ppk_times = [datetime.strptime(normalize_date(ppk[0]) + ' ' + ppk[1], '%m/%d/%Y %H:%M:%S.%f') for ppk in self.ppk_data]
        
        if min(image_times) > max(ppk_times) or max(image_times) < min(ppk_times):
            QMessageBox.warning(self, "Time Mismatch", "Image timestamps do not overlap with PPK data timestamps.")
            return

        # Initialize the progress dialog
        progress = QProgressDialog("Updating Images Geolocations...", "Cancel", 0, len(all_images), self)
        progress.setWindowTitle("Geotagging")
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)

        # Interpolate and update image geolocations
        updated_image_data = []
        for idx, image in enumerate(all_images):
            image_time = datetime.strptime(normalize_date(image[4]) + ' ' + image[5], '%Y/%m/%d %H:%M:%S')

            # Find the nearest PPK times surrounding the image time
            ppk_before = max([ppk for ppk in self.ppk_data if datetime.strptime(normalize_date(ppk[0]) + ' ' + ppk[1], '%m/%d/%Y %H:%M:%S.%f') <= image_time], key=lambda ppk: datetime.strptime(normalize_date(ppk[0]) + ' ' + ppk[1], '%m/%d/%Y %H:%M:%S.%f'))
            ppk_after = min([ppk for ppk in self.ppk_data if datetime.strptime(normalize_date(ppk[0]) + ' ' + ppk[1], '%m/%d/%Y %H:%M:%S.%f') >= image_time], key=lambda ppk: datetime.strptime(normalize_date(ppk[0]) + ' ' + ppk[1], '%m/%d/%Y %H:%M:%S.%f'))

            # Interpolate the latitude, longitude, and altitude
            time_before = datetime.strptime(normalize_date(ppk_before[0]) + ' ' + ppk_before[1], '%m/%d/%Y %H:%M:%S.%f')
            time_after = datetime.strptime(normalize_date(ppk_after[0]) + ' ' + ppk_after[1], '%m/%d/%Y %H:%M:%S.%f')

            if time_before == time_after:
                interpolated_lat = ppk_before[2]
                interpolated_lon = ppk_before[3]
                interpolated_alt = ppk_before[4]
            else:
                total_time_diff = (time_after - time_before).total_seconds()
                time_diff_before = (image_time - time_before).total_seconds()

                ratio = time_diff_before / total_time_diff
                interpolated_lat = ppk_before[2] + ratio * (ppk_after[2] - ppk_before[2])
                interpolated_lon = ppk_before[3] + ratio * (ppk_after[3] - ppk_before[3])
                interpolated_alt = ppk_before[4] + ratio * (ppk_after[4] - ppk_before[4])

            # Update image data with the interpolated values
            updated_image_data.append([os.path.basename(image[0]), interpolated_lat, interpolated_lon, interpolated_alt])

            # Update the progress dialog
            progress.setValue(idx + 1)
            if progress.wasCanceled():
                break

        # Export updated geolocations to a CSV file
        export_filename, _ = QFileDialog.getSaveFileName(self, "Save Updated Geolocations", "", "CSV Files (*.csv)")
        if export_filename:
            try:
                with open(export_filename, mode='w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(['Image Filename', 'Latitude', 'Longitude', 'Altitude'])
                    for row in updated_image_data:
                        writer.writerow(row)
                QMessageBox.information(self, "Success", "Updated geolocations exported successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export geolocations: {e}")


    def showmap(self):
        # Check if there's any data to show
        if not self.image_sets and not self.ppk_data:
            QMessageBox.warning(self, "No Data", "No layers to be shown.")
            return

        # Initialize bounding box values
        min_lat, min_lon = float('inf'), float('inf')
        max_lat, max_lon = float('-inf'), float('-inf')

        # Create the map with a default location, it will be adjusted later
        m = folium.Map(location=[0, 0], zoom_start=2)
        data_added = False  # To track if any data was added to the map

        # Feature groups for layers
        image_layer = folium.FeatureGroup(name="Image Locations")
        ppk_layer = folium.FeatureGroup(name="PPK Path")

        # If image sets exist, plot them on the image_layer
        if self.image_sets:
            for imageset in self.image_sets:
                for image in imageset:
                    lat = dms_to_decimal(*image[1])
                    lon = dms_to_decimal(*image[2])
                    folium.Marker(
                        [lat, lon],
                        tooltip=os.path.basename(image[0]),
                        icon=folium.Icon(icon="camera", prefix="fa")
                    ).add_to(image_layer)
                    data_added = True

                    # Update bounding box
                    min_lat = min(min_lat, lat)
                    max_lat = max(max_lat, lat)
                    min_lon = min(min_lon, lon)
                    max_lon = max(max_lon, lon)

        # If PPK data exists, plot the path on the ppk_layer
        if self.ppk_data:
            ppk_path = []
            for date, time, lat, lon, alt in self.ppk_data:
                ppk_path.append([lat, lon])

                # Update bounding box
                min_lat = min(min_lat, lat)
                max_lat = max(max_lat, lat)
                min_lon = min(min_lon, lon)
                max_lon = max(max_lon, lon)

            # Add the PPK path as a polyline to the ppk_layer
            folium.PolyLine(ppk_path, color="blue", weight=2.5, opacity=1).add_to(ppk_layer)
            data_added = True

        # Add layers to the map
        if data_added:
            if self.image_sets:
                image_layer.add_to(m)
            if self.ppk_data:
                ppk_layer.add_to(m)

            # Add layer control to the map
            folium.LayerControl().add_to(m)

            # Adjust the map view to fit the data
            # Calculate the center of the bounding box
            center_lat = (min_lat + max_lat) / 2
            center_lon = (min_lon + max_lon) / 2
            m.location = [center_lat, center_lon]
            folium.FitBounds([[min_lat, min_lon], [max_lat, max_lon]]).add_to(m)

            # Save and display the map
            map_html = "map.html"
            m.save(map_html)

            self.map_view = QWebEngineView()
            self.map_view.setWindowTitle("Image and PPK Locations")
            self.map_view.resize(800, 600)
            self.map_view.setUrl(QUrl.fromLocalFile(os.path.abspath(map_html)))
            self.map_view.show()
        else:
            # If no data was added to the map, warn the user
            QMessageBox.warning(self, "No Data", "No layers to be shown.")

    def apply_corrections(self):
        if not self.corrections or not self.image_sets:
            return

        corrections_found = set()
        unmatched_corrections = []

        for i, imageset in enumerate(self.image_sets):
            try:
                # Parsing the image set's start date and time
                start_date_str = imageset[0][4]  # 'YYYY:mm:dd'
                start_time_str = imageset[0][5]  # 'HH:MM:SS'
                start_date = datetime.strptime(start_date_str, '%Y:%m:%d').date()  # Extract just the date
                start_datetime = datetime.strptime(start_date_str + ' ' + start_time_str, '%Y:%m:%d %H:%M:%S')
            except ValueError as e:
                print(f"Error parsing date for image set {i}: {e}")
                unmatched_corrections.append(i)
                continue  # Skip to the next image set if parsing fails

            applicable_correction = None

            # Iterate through corrections to find the latest one with the same date and before the start time
            for correction in self.corrections:
                try:
                    # Parsing the correction's date and time
                    corr_datetime = datetime.strptime(correction['Date/Time'], '%m/%d/%Y %H:%M')
                    corr_date = corr_datetime.date()  # Extract just the date
                except ValueError as e:
                    print(f"Error parsing correction date: {e}")
                    continue  # Skip this correction if parsing fails

                # First, compare the dates
                if corr_date == start_date:
                    # If the dates match, then compare the times
                    if corr_datetime.time() < start_datetime.time():  # Check time separately
                        applicable_correction = correction
                    else:
                        break  # Corrections are sorted, so stop checking once times no longer match
                elif corr_date > start_date:
                    break  # Since corrections are sorted, stop if the correction date is later than the image set's date

            if applicable_correction:
                # Extract the deltas and apply the correction to the table
                delta_lat = float(applicable_correction['deltaLat'])
                delta_lon = float(applicable_correction['deltaLong'])
                delta_alt = float(applicable_correction['deltah'])

                self.tableWidget.setItem(i, 4, QTableWidgetItem(f"{delta_lat:.8f}"))  # Display with full precision
                self.tableWidget.setItem(i, 5, QTableWidgetItem(f"{delta_lon:.8f}"))  # Display with full precision
                self.tableWidget.setItem(i, 6, QTableWidgetItem(f"{delta_alt:.4f}"))  # Display with full precision
                corrections_found.add(applicable_correction['Point Id'])
            else:
                unmatched_corrections.append(i)

        # Find corrections that were not used
        correction_ids = {c['Point Id'] for c in self.corrections}
        unused_corrections = correction_ids - corrections_found

        if unused_corrections:
            QMessageBox.warning(
                self,
                "Unmatched Corrections",
                f"The following corrections did not match any image sets:\n"
                + "\n".join(unused_corrections)
            )




    def table_double_clicked(self, index):
        set_index = index.row()
        current_lat = float(self.tableWidget.item(set_index, 4).text())
        current_lon = float(self.tableWidget.item(set_index, 5).text())
        current_alt = float(self.tableWidget.item(set_index, 6).text())
        dialog = CorrectionDialog(current_lat, current_lon, current_alt, self)
        if dialog.exec_():
            lat_shift, lon_shift, alt_shift = dialog.get_corrections()
            self.tableWidget.setItem(set_index, 4, QTableWidgetItem(f"{lat_shift:.9f}"))
            self.tableWidget.setItem(set_index, 5, QTableWidgetItem(f"{lon_shift:.9f}"))
            self.tableWidget.setItem(set_index, 6, QTableWidgetItem(f"{alt_shift:.6f}"))


    def export_all_sets(self):
        if not self.image_sets:
            QMessageBox.warning(self, "No Data", "No sets loaded.")
            return

        dialog = ExportSelectionDialog(self.image_sets, self)
        if dialog.exec_():
            selected_indices = dialog.get_selected_indices()
            filename = QFileDialog.getSaveFileName(self, "Save File", "", "CSV Files (*.csv)")
            if filename[0]:
                with open(filename[0], 'w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(['ID', 'Latitude', 'Longitude', 'Altitude'])
                    for i in selected_indices:
                        imageset = self.image_sets[i]
                        lat_shift_item = self.tableWidget.item(i, 4)
                        lon_shift_item = self.tableWidget.item(i, 5)
                        alt_shift_item = self.tableWidget.item(i, 6)
                        lat_shift = float(lat_shift_item.text()) if lat_shift_item else 0.0
                        lon_shift = float(lon_shift_item.text()) if lon_shift_item else 0.0
                        alt_shift = float(alt_shift_item.text()) if alt_shift_item else 0.0
                        for image in imageset:
                            adjusted_lat = dms_to_decimal(*image[1]) + lat_shift
                            adjusted_lon = dms_to_decimal(*image[2]) + lon_shift
                            adjusted_alt = image[3] + alt_shift
                            writer.writerow([
                                os.path.basename(image[0]), 
                                f"{adjusted_lat:.9f}", 
                                f"{adjusted_lon:.9f}", 
                                f"{adjusted_alt:.6f}"
                            ])

def main():
    app = QApplication(sys.argv)
    ex = MainWindow()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()