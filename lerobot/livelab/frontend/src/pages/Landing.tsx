import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { Camera, Mic, Settings } from "lucide-react";

const Landing = () => {
  const [robotModel, setRobotModel] = useState("");
  const [showPermissionModal, setShowPermissionModal] = useState(false);
  const [showTeleoperationModal, setShowTeleoperationModal] = useState(false);
  const [leaderPort, setLeaderPort] = useState("/dev/tty.usbmodem5A460816421");
  const [followerPort, setFollowerPort] = useState(
    "/dev/tty.usbmodem5A460816621"
  );
  const [leaderConfig, setLeaderConfig] = useState("");
  const [followerConfig, setFollowerConfig] = useState("");
  const [leaderConfigs, setLeaderConfigs] = useState<string[]>([]);
  const [followerConfigs, setFollowerConfigs] = useState<string[]>([]);
  const [isLoadingConfigs, setIsLoadingConfigs] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();

  const loadConfigs = async () => {
    setIsLoadingConfigs(true);
    try {
      const response = await fetch("http://localhost:8000/get-configs");
      const data = await response.json();
      setLeaderConfigs(data.leader_configs || []);
      setFollowerConfigs(data.follower_configs || []);
    } catch (error) {
      toast({
        title: "Error Loading Configs",
        description: "Could not load calibration configs from the backend.",
        variant: "destructive",
      });
    } finally {
      setIsLoadingConfigs(false);
    }
  };

  const handleBeginSession = () => {
    if (robotModel) {
      setShowPermissionModal(true);
    }
  };

  const handleTeleoperationClick = () => {
    if (robotModel) {
      setShowTeleoperationModal(true);
      loadConfigs();
    }
  };

  const handleStartTeleoperation = async () => {
    if (!leaderConfig || !followerConfig) {
      toast({
        title: "Missing Configuration",
        description:
          "Please select calibration configs for both leader and follower.",
        variant: "destructive",
      });
      return;
    }

    try {
      const response = await fetch("http://localhost:8000/move-arm", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          leader_port: leaderPort,
          follower_port: followerPort,
          leader_config: leaderConfig,
          follower_config: followerConfig,
        }),
      });

      const data = await response.json();

      if (response.ok) {
        toast({
          title: "Teleoperation Started",
          description:
            data.message || "Successfully started teleoperation session.",
        });
        setShowTeleoperationModal(false);
        navigate("/teleoperation");
      } else {
        toast({
          title: "Error Starting Teleoperation",
          description: data.message || "Failed to start teleoperation session.",
          variant: "destructive",
        });
      }
    } catch (error) {
      toast({
        title: "Connection Error",
        description: "Could not connect to the backend server.",
        variant: "destructive",
      });
    }
  };

  const handlePermissions = async (allow: boolean) => {
    setShowPermissionModal(false);
    if (allow) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: true,
          audio: true,
        });
        stream.getTracks().forEach((track) => track.stop());
        toast({
          title: "Permissions Granted",
          description:
            "Camera and microphone access enabled. Entering control session...",
        });
        navigate("/control");
      } catch (error) {
        toast({
          title: "Permission Denied",
          description:
            "Camera and microphone access is required for robot control.",
          variant: "destructive",
        });
      }
    } else {
      toast({
        title: "Permission Denied",
        description: "You can proceed, but with limited functionality.",
        variant: "destructive",
      });
      navigate("/control");
    }
  };

  return (
    <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-4">
      <div className="text-center space-y-4 max-w-lg w-full">
        <img
          src="/lovable-uploads/5e648747-34b7-4d8f-93fd-4dbd00aeeefc.png"
          alt="LiveLab Logo"
          className="mx-auto h-20 w-20"
        />
        <h1 className="text-5xl font-bold tracking-tight">LiveLab</h1>
        <p className="text-xl text-gray-400">
          Control a robotic arm through telepresence. Your browser becomes both
          sensor and controller.
        </p>
      </div>

      <div className="mt-12 p-8 bg-gray-900 rounded-lg shadow-xl w-full max-w-lg space-y-6 border border-gray-700">
        <h2 className="text-2xl font-semibold text-center text-white">
          Select Robot Model
        </h2>
        <RadioGroup
          value={robotModel}
          onValueChange={setRobotModel}
          className="space-y-4"
        >
          <div>
            <RadioGroupItem value="SO100" id="so100" className="sr-only" />
            <Label
              htmlFor="so100"
              className="flex items-center space-x-4 p-4 rounded-md bg-gray-800 border border-gray-700 cursor-pointer transition-all has-[:checked]:border-orange-500 has-[:checked]:bg-gray-800/50"
            >
              <span className="w-6 h-6 rounded-full border-2 border-gray-500 flex items-center justify-center group-has-[:checked]:border-orange-500">
                {robotModel === "SO100" && (
                  <span className="w-3 h-3 rounded-full bg-orange-500" />
                )}
              </span>
              <span className="text-lg flex-1">SO100</span>
            </Label>
          </div>
          <div>
            <RadioGroupItem value="SO101" id="so101" className="sr-only" />
            <Label
              htmlFor="so101"
              className="flex items-center space-x-4 p-4 rounded-md bg-gray-800 border border-gray-700 cursor-pointer transition-all has-[:checked]:border-orange-500 has-[:checked]:bg-gray-800/50"
            >
              <span className="w-6 h-6 rounded-full border-2 border-gray-500 flex items-center justify-center group-has-[:checked]:border-orange-500">
                {robotModel === "SO101" && (
                  <span className="w-3 h-3 rounded-full bg-orange-500" />
                )}
              </span>
              <span className="text-lg flex-1">SO101</span>
            </Label>
          </div>
        </RadioGroup>
        <div className="flex flex-col sm:flex-row gap-4">
          <Button
            onClick={handleBeginSession}
            disabled={!robotModel}
            className="flex-1 bg-orange-500 hover:bg-orange-600 text-white text-lg py-6 disabled:bg-gray-700 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Begin Session
          </Button>
          <Button
            onClick={handleTeleoperationClick}
            disabled={!robotModel}
            className="flex-1 bg-yellow-500 hover:bg-yellow-600 text-white text-lg py-6 disabled:bg-gray-700 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Teleoperation
          </Button>
        </div>
      </div>

      {/* Permission Modal */}
      <Dialog open={showPermissionModal} onOpenChange={setShowPermissionModal}>
        <DialogContent className="bg-gray-900 border-gray-800 text-white sm:max-w-[480px] p-8">
          <DialogHeader>
            <div className="flex justify-center items-center gap-4 mb-4">
              <Camera className="w-8 h-8 text-orange-500" />
              <Mic className="w-8 h-8 text-orange-500" />
            </div>
            <DialogTitle className="text-white text-center text-2xl font-bold">
              Enable Camera & Microphone
            </DialogTitle>
          </DialogHeader>
          <div className="text-center space-y-6 py-4">
            <DialogDescription className="text-gray-400 text-base leading-relaxed">
              LiveLab requires access to your camera and microphone for a fully
              immersive telepresence experience. This enables real-time video
              feedback and voice command capabilities.
            </DialogDescription>
            <div className="flex flex-col sm:flex-row gap-4 justify-center pt-2">
              <Button
                onClick={() => handlePermissions(true)}
                className="w-full sm:w-auto bg-orange-500 hover:bg-orange-600 text-white px-10 py-6 text-lg transition-all shadow-md shadow-orange-500/30 hover:shadow-lg hover:shadow-orange-500/40"
              >
                Allow Access
              </Button>
              <Button
                onClick={() => handlePermissions(false)}
                variant="outline"
                className="w-full sm:w-auto border-gray-500 hover:border-gray-200 px-10 py-6 text-lg text-zinc-500 bg-zinc-900 hover:bg-zinc-800"
              >
                Continue without
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Teleoperation Configuration Modal */}
      <Dialog
        open={showTeleoperationModal}
        onOpenChange={setShowTeleoperationModal}
      >
        <DialogContent className="bg-gray-900 border-gray-800 text-white sm:max-w-[600px] p-8">
          <DialogHeader>
            <div className="flex justify-center items-center gap-4 mb-4">
              <Settings className="w-8 h-8 text-yellow-500" />
            </div>
            <DialogTitle className="text-white text-center text-2xl font-bold">
              Configure Teleoperation
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-6 py-4">
            <DialogDescription className="text-gray-400 text-base leading-relaxed text-center">
              Configure the robot arm ports and calibration settings for
              teleoperation.
            </DialogDescription>

            <div className="grid grid-cols-1 gap-6">
              <div className="space-y-2">
                <Label
                  htmlFor="leaderPort"
                  className="text-sm font-medium text-gray-300"
                >
                  Leader Port
                </Label>
                <Input
                  id="leaderPort"
                  value={leaderPort}
                  onChange={(e) => setLeaderPort(e.target.value)}
                  placeholder="/dev/tty.usbmodem5A460816421"
                  className="bg-gray-800 border-gray-700 text-white"
                />
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="leaderConfig"
                  className="text-sm font-medium text-gray-300"
                >
                  Leader Calibration Config
                </Label>
                <Select value={leaderConfig} onValueChange={setLeaderConfig}>
                  <SelectTrigger className="bg-gray-800 border-gray-700 text-white">
                    <SelectValue
                      placeholder={
                        isLoadingConfigs
                          ? "Loading configs..."
                          : "Select leader config"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700">
                    {leaderConfigs.map((config) => (
                      <SelectItem
                        key={config}
                        value={config}
                        className="text-white hover:bg-gray-700"
                      >
                        {config}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="followerPort"
                  className="text-sm font-medium text-gray-300"
                >
                  Follower Port
                </Label>
                <Input
                  id="followerPort"
                  value={followerPort}
                  onChange={(e) => setFollowerPort(e.target.value)}
                  placeholder="/dev/tty.usbmodem5A460816621"
                  className="bg-gray-800 border-gray-700 text-white"
                />
              </div>

              <div className="space-y-2">
                <Label
                  htmlFor="followerConfig"
                  className="text-sm font-medium text-gray-300"
                >
                  Follower Calibration Config
                </Label>
                <Select
                  value={followerConfig}
                  onValueChange={setFollowerConfig}
                >
                  <SelectTrigger className="bg-gray-800 border-gray-700 text-white">
                    <SelectValue
                      placeholder={
                        isLoadingConfigs
                          ? "Loading configs..."
                          : "Select follower config"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent className="bg-gray-800 border-gray-700">
                    {followerConfigs.map((config) => (
                      <SelectItem
                        key={config}
                        value={config}
                        className="text-white hover:bg-gray-700"
                      >
                        {config}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
              <Button
                onClick={handleStartTeleoperation}
                className="w-full sm:w-auto bg-yellow-500 hover:bg-yellow-600 text-white px-10 py-6 text-lg transition-all shadow-md shadow-yellow-500/30 hover:shadow-lg hover:shadow-yellow-500/40"
                disabled={isLoadingConfigs}
              >
                Start Teleoperation
              </Button>
              <Button
                onClick={() => setShowTeleoperationModal(false)}
                variant="outline"
                className="w-full sm:w-auto border-gray-500 hover:border-gray-200 px-10 py-6 text-lg text-zinc-500 bg-zinc-900 hover:bg-zinc-800"
              >
                Cancel
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Landing;
