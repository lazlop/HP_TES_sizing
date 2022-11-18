import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, date, time
import matplotlib.dates as mdates

from scipy.integrate import trapz

class HPsizer():

    def __init__(self, file, charge_p, discharge_p, day = None, index_col = None, value_col = None, method = 'highest_ave'):

        #can't parse_dates without knowing the index_column
        df = pd.read_csv(file)

        # TODO:
        # assuming column name based on order, should add in some error catching
        # Can assume columns based on if they can be parsed to datetime as well
        if not index_col:
            self.index_col  = df.columns[0]
        else:
            self.index_col = index_col

        if not value_col:
            self.value_col = df.columns[1]
        else:
            self.value_col = value_col
        
        df.index = pd.to_datetime(df[self.index_col])
        df[self.value_col] = df[self.value_col].apply(self.parse_val_string)
      
        # TODO: Change to allow other granularities of data?
        self.df = self.get_df(df, day, method)
        self.charge_ser = self.get_period(self.df, charge_p)
        self.peak_ser = self.get_period(self.df, discharge_p)
       
        self.peak_energy = trapz(self.peak_ser.values, dx=1/60)

        # should I get this from peak_ser or whole day?
        self.hp_size_max = self.df.values.max() 

        self.charge_p = charge_p
        self.discharge_p = discharge_p

        self.point_1 = (self.hp_size_max, 0)

    def get_df(self, df, day, method):
        # Can try different aggregation methods here
        groups = df.groupby(df.index.date)
        if day:
            day = datetime.strptime(day, '%Y-%m-%d').date()
            df = groups.get_group(day)
        elif method == 'peak_load':
            day = df.loc[df[self.value_col] == df[self.value_col].max()].index[0].date
            df = groups.get_group(day)
        # Highest average load
        elif method == 'highest_ave':
            mean_df = groups.mean()
            day = mean_df.loc[mean_df[self.value_col] == mean_df.max()[0]].index[0]
            df = groups.get_group(day)
        #Average of 7 highest load days
        elif method == 'highest_7_days':
            groups = df.groupby(df.index.date)
            mean_df = groups.mean()
            days = mean_df.sort_values(by = self.value_col, ascending=False).index[:7]
            df = self.average_days(df, days)
            print(f'df represents days {days}')
        # resampling any granularity of data to 1 minute
        df = df.resample('1T').interpolate().resample('1T').mean()
        df.index = df.index.time
        return df
    
    def average_days(self, df, days):
       # df=df.reset_index()
        df['date']=df.index.date
        df['time']=df.index.time
        df_day = df.loc[df.date.isin(days)].groupby('time').mean()
        # had to add below to make resample work
        now = datetime.now()
        df_day.index = pd.Series(df_day.index).apply( 
            lambda x: now.replace(hour = x.hour, minute = x.minute, second = x.second) 
            )
        return df_day

    def get_period(self, df, period):
        if period[0] > period[1]:
            return df.loc[(df.index >= time(period[0])) | (df.index < time(period[1])), self.value_col]
        else:
            return df.loc[time(period[0]): time(period[1]), self.value_col]
        #should have error if period is the same hour

    def _tes_size(self, hp_size):
        # should add something to make sure load is ALWAYS satisfied
        # return hp_size * (self.charge_p[1] - self.charge_p[0] + 24)# engineering estimation, HP size * duration of charge
        return (hp_size - self.charge_ser).sum()/60 # ALL unused HP capacity goes to TES

    def sizing_plot(self):
        fig = plt.figure()
        x, y = self._bottom()
        x2,y2= self._top()
        x3,y3 = self._right()
        plt.plot(x,y)
        plt.plot(x2,y2)
        plt.plot(x3,y3)
        plt.xlabel('HP Capacity (kW)')
        plt.ylabel('TES Size (kWh)')
        plt.show()
    
    # def plot_series(self, ser):
    #     plt.ylabel('kW')
    #     # plt.ylim(ymin = 0, ymax=self.ymax)
    #     plt.plot(ser)
    #     t_fmt = mdates.DateFormatter('%H:%M')
    #     plt.gca().xaxis.set_major_formatter(t_fmt)
    # #       plt.xticks(rotation=45)
    #     plt.show()


    def _bottom(self):

        hp_size = self.hp_size_max
        size_reduction = -0.0005 

        x = []
        y = []
        for i in range(0,100000):
        
            hp_size = hp_size + size_reduction * i
            power_from_TES = self.peak_ser.loc[self.peak_ser - hp_size > 0]
            
            #using .loc doesn't negatively effect this method (having 0 is equivalent to no value there)
            TES_size = trapz(self.peak_ser.loc[self.peak_ser - hp_size > 0], dx = 1/60)
            
            #doing rhieman sum is essentially the same though
            #TES_size = self.peak_ser.loc[self.peak_ser - hp_size > 0].sum()/60 

            x.append(hp_size)
            y.append(TES_size)

            if TES_size > self._tes_size(hp_size):
                break
            
        self.point_2 = (hp_size,TES_size)

        return x, y

    def _top(self):
        # MUST run bottom before top
        x = []
        y = []
        hp_size = self.hp_size_max
        size_reduction = -0.0005 

        for i in range(0,100000):
            hp_size = hp_size + size_reduction * i

            # may want to draw top, then another line for the maximum based on peak energy provided by TES
            TES_size = self._tes_size(hp_size) # should subtract load in this period to make better estimate

            if TES_size > self.peak_energy:
                y.append(self.peak_energy)
            else:
                y.append(TES_size)
            x.append(hp_size)

            if hp_size <= self.point_2[0]: # This is cheating a bit
                break
            
        return x, y

    def _right(self):
        # This whole function is cheaty
        x = []
        y = []

        x.append(self.point_1[0])
        x.append(self.point_1[0])

        y.append(self.peak_energy)
        y.append(0)

        return x,y 
             

    def parse_val_string(self, str_val):
        if str(str_val).isnumeric():
            raise(Warning('no units supplied, assuming W'))
            return float(str_val)
        str_splt = str_val.split(' ')
        if str_splt[1] == 'kW':
            return float(str_splt[0])
        elif str_splt[1] == 'W':
            return float(str_splt[0])/1000
        elif str_splt[1] == 'mW':
            return float(str_splt[0])/1000000
        elif str_splt[1] == 'µW':
            return float(str_splt[0])/1000000000  
        else:
            print(str_val)
            #return 0 
            raise(Exception('not kW or W or mW or µW'))