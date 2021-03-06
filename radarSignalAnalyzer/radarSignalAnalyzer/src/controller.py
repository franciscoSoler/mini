from PyQt5 import QtCore
import numpy as np
import scipy as sp
import logging
import enum
import os

import radarSignalAnalyzer.src.utils.config_file_manager as cfm
import radarSignalAnalyzer.src.utils.gaussian_calculator as gc
import radarSignalAnalyzer.src.signal_processor.signal_processor as sign_proc
import radarSignalAnalyzer.src.signal_receiver.real_receiver as r_receiver
import radarSignalAnalyzer.src.signal_receiver.file_receiver as f_receiver
import radarSignalAnalyzer.src.distance_calculator as calculator
import radarSignalAnalyzer.src.common as common
import radarSignalAnalyzer.src.signal_base as sign

np.seterr(all='raise')


class Measurement(enum.Enum):
    Gain = 1
    Phase = 2
    Distance = 3


class Controller(QtCore.QObject):

    update_data = QtCore.pyqtSignal(float, tuple, float, tuple, tuple, float, float, float)

    def __init__(self, max_freq, real_time=True):
        super(Controller, self).__init__()
        self.__logger = logging.getLogger(__name__)
        self.__signal_processor = sign_proc.SignalProcessor(os.path.join(os.path.dirname(__file__), common.CONFIG_PATH))
        self.__measure_clutter = False

        self.__max_freq = max_freq
        self.__receiver = None
        self.__num_samples = None
        self.__clutter = None
        self.__freq_points = None
        self.__quantity_freq_samples = None

        self.set_real_time_mode(real_time)
        self.__samples_to_cut = 0
        self.__use_external_clutter = False
        self.__ext_clutter = None

        self.__distance_from_gui = 0
        self.__use_distance_from_gui = False

        self.__measurements = {me: gc.GaussianCalculator() for me in Measurement}
        self.__cut = np.pi
        self.__initialize()

    def __initialize(self):
        manager = cfm.ConfigFileManager(os.path.join(os.path.dirname(__file__), common.CONFIG_PATH))
        self.__samples_to_cut = int(manager.get_parameter(cfm.ConfTags.SAMPCUT))

    def __initialize_singal_properties(self):
        """Align every property to the receiving signal."""
        self.__num_samples = self.__receiver.get_num_samples_per_period()

        while not self.__num_samples:
            self.__num_samples = self.__receiver.get_num_samples_per_period()

        self.__clutter = sign.Signal([0]*self.__num_samples)
        self.__freq_points = int(np.exp2(np.ceil(np.log2(self.__num_samples))+7))
        self.__quantity_freq_samples = int(self.__max_freq*self.__freq_points//self.__receiver.sampling_rate)
        self.__logger.debug('Frequency samples to calculate the FFT: %d', self.__quantity_freq_samples)

    @property
    def signal_length(self):
        return self.__num_samples - self.__samples_to_cut

    @property
    def freq_length(self):
        return self.__quantity_freq_samples

    def get_signal_range(self):
        d_t = 1/self.__receiver.sampling_rate
        return np.linspace(0, d_t * self.signal_length, num=self.signal_length, endpoint=False)

    def get_frequency_range(self):
        d_f = self.__receiver.sampling_rate/self.__freq_points
        return np.arange(0, (d_f*self.__freq_points)//2, d_f)[:self.__quantity_freq_samples]

    def get_disance_from_freq(self, freq):
        signal = self.__receiver.get_audio_data(self.__num_samples)
        return signal.period * freq*common.C/(2*signal.bandwidth)

    def __process_reception(self, signal):
        signal.cut(self.__samples_to_cut)
        self.__signal_processor.process_signal(signal, self.__freq_points)
        calc_dist, delta_r = self.__signal_processor.get_processed_distance()
        frequency, d_f = self.__signal_processor.get_processed_frequency()

        distance = self.__distance_from_gui if self.__use_distance_from_gui else calc_dist

        gain, tg_phase, rtt_ph = self.__signal_processor.calculate_target_properties_from_distance(signal, distance)

        gain_to_tg = self.__signal_processor.calculate_gain_to_target(distance)

        if not self.__measurements[Measurement.Phase].n:
            if np.pi > tg_phase > np.pi/2:
                self.__cut = 0

            elif -np.pi/2 > tg_phase > -np.pi:
                self.__cut = 2 * np.pi

            else:
                self.__cut = np.pi

        self.__measurements[Measurement.Distance].add_sample(calc_dist)
        self.__measurements[Measurement.Gain].add_sample(gain)
        self.__measurements[Measurement.Phase].add_sample(np.rad2deg(common.format_phase(tg_phase, self.__cut)))

        calc_dist = self.__measurements[Measurement.Distance].get_mean_std(n=3, decimals=3)
        tg_gain = self.__measurements[Measurement.Gain].get_mean_std(n=3, decimals=4)
        tg_ph = self.__measurements[Measurement.Phase].get_mean_std(n=3, decimals=1)

        self.update_data.emit(round(d_f, 3), calc_dist, round(delta_r, 6), tg_gain, tg_ph, round(gain_to_tg, 8),
                              round(np.rad2deg(rtt_ph), 1), round(distance, 4))

        if signal.length > self.signal_length:
            data = signal.signal[:self.signal_length]
        else:
            data = np.concatenate((signal.signal, [0]*(self.signal_length-signal.length)))

        return data, abs(frequency[:self.__quantity_freq_samples]), np.rad2deg(tg_phase)

    def run(self, t=0):
        signal = self.__receiver.get_audio_data(self.__num_samples)

        if self.__measure_clutter:
            self.__measure_clutter = False

            if self.__use_external_clutter:
                self.__logger.info('Measuring clutter from an external signal')
                self.__clutter.signal = self.__ext_clutter.signal*signal.applied_volume
            else:
                self.__logger.info('Measuring clutter from the reproduced signal')
                self.__clutter.signal = signal.signal

            self.__clutter.applied_volume = signal.applied_volume
            self.__clutter.frequency_sampling = signal.frequency_sampling

        signal.subtract_signals(self.__clutter)

        yield self.__process_reception(signal)

    def remove_clutter(self):
        self.__logger.info('Start removing the clutter from the signal')
        self.__measure_clutter = True

    def restore_clutter(self):
        self.__logger.info('Stop removing the clutter from the signal')
        if self.__clutter is None:
            return

        self.__clutter.signal = np.zeros(self.__clutter.length)

    def set_distance_from_gui(self, distance):
        self.__logger.info('Using the distance from GUI with value %f', distance)
        self.__use_distance_from_gui = True
        self.__distance_from_gui = distance
        self.reset_statistics()

    def remove_distance(self):
        self.__logger.info('Stop using the distance from GUI')
        if self.__use_distance_from_gui:
            self.reset_statistics()

        self.__use_distance_from_gui = False

    def reset_statistics(self):
        self.__logger.info('Resetting statistics')
        self.__measurements = {me: gc.GaussianCalculator() for me in Measurement}

    def rewind_audio(self):
        self.__logger.info('Rewinding audio')
        self.reset_statistics()
        self.__receiver.rewind()

    def set_auto_rewind(self, auto):
        self.__logger.info('Auto rewind mode {}'.format('ON' if auto else 'OFF'))
        self.__receiver.auto_rewind = auto

    def set_volume(self, volume):
        self.__logger.info("Changing the signal's volume to: %f".format(volume))
        self.__receiver.volume = volume

    def reset_volume(self):
        self.__logger.info('Resetting the volume to its original value')
        self.__receiver.reset_volume()

    def increase_volume(self):
        self.__logger.info('Increasing volume by one')
        increment = 1
        self.__receiver.modify_volume(increment)
        return increment

    def decrease_volume(self):
        self.__logger.info('Decreasing volume by one')
        decrement = 1
        self.__receiver.modify_volume(-decrement)
        return decrement

    def use_external_signal(self, file_path):
        self.__logger.info('Opening external signal: ' + file_path)
        self.__receiver.track = file_path
        self.reset_statistics()
        self.__initialize_singal_properties()

    def use_external_clutter(self, file_path):
        self.__logger.info('Opening external clutter: ' + file_path)
        receiver = f_receiver.FileReceiver(file_path)
        self.reset_statistics()
        self.__ext_clutter = receiver.get_audio_data(self.__num_samples)
        self.__use_external_clutter = True
        receiver.stop()

    def stop_using_external_clutter(self):
        self.__logger.info('Clutter removal has stopped')
        self.__use_external_clutter = False

    def set_real_time_mode(self, real_time=True):
        self.__logger.info('Real Time mode {}'.format('ON' if real_time else 'OFF'))
        if self.__receiver is not None:
            self.__logger.info('Stopping the previous receiver')
            self.__receiver.stop()

        self.__receiver = r_receiver.RealReceiver() if real_time else f_receiver.FileReceiver()
        self.reset_statistics()

        if real_time:
            self.__initialize_singal_properties()
