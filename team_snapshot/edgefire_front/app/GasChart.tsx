"use client";

import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from "recharts";

const sensorDataMap: Record<string, Array<{ time: string; CO: number; H2: number }>> = {
  "GAS-Node-01": [
    { time: "14:00", CO: 12, H2: 5 },
    { time: "14:05", CO: 15, H2: 7 },
    { time: "14:10", CO: 14, H2: 6 },
  ],
  "GAS-Node-02": [
    { time: "14:00", CO: 25, H2: 12 },
    { time: "14:05", CO: 45, H2: 20 },
    { time: "14:10", CO: 85, H2: 38 },
  ],
};

export default function GasChart({ selectedSensorId }: { selectedSensorId: string }) {
  const currentData = sensorDataMap[selectedSensorId] || sensorDataMap["GAS-Node-02"];

  return (
    <div className="w-full h-full text-xs min-h-[180px]">
      <ResponsiveContainer width="100%" height="100%" minWidth={100} minHeight={100}>
        <LineChart data={currentData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="time" stroke="#9CA3AF" />
          <YAxis stroke="#9CA3AF" />
          <Tooltip contentStyle={{ backgroundColor: "#1F2937", borderColor: "#374151", color: "#FFF" }} />
          <Legend wrapperStyle={{ paddingTop: "5px" }} />
          <Line type="monotone" dataKey="CO" name="CO (일산화탄소)" stroke="#EF4444" strokeWidth={2} dot={{ r: 3 }} />
          <Line type="monotone" dataKey="H2" name="H2 (수소)" stroke="#3B82F6" strokeWidth={2} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}