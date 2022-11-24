# ELO
# python 3.4.3
import math

_ELO_CONSTANT = 60

class ELOPlayer:
    def __init__(self):
        self.name = ""
        self.place = 0
        self.eloPre = 0
        self.eloPost = 0
        self.eloChange = 0


class ELOMatch:
    def __init__(self):
        self.players = []

    def addPlayer(self, name, place, elo):
        player = ELOPlayer()

        player.name = name
        player.place = place
        player.eloPre = elo

        self.players.append(player)

    def getELO(self, name):
        for p in self.players:
            if p.name == name:
                return p.eloPost

        return 1500

    def getELOChange(self, name):
        for p in self.players:
            if p.name == name:
                return p.eloChange

        return 0

    def calculateELOs(self):
        n = len(self.players)
        K = _ELO_CONSTANT / max(1, (n - 1))

        for i in range(n):
            curPlace = self.players[i].place
            curELO = self.players[i].eloPre

            for j in range(n):
                if i != j:
                    opponentPlace = self.players[j].place
                    opponentELO = self.players[j].eloPre

                    # work out S
                    if curPlace < opponentPlace:
                        S = 1.0
                    elif curPlace == opponentPlace:
                        S = 0.5
                    else:
                        S = 0.0

                    # work out EA
                    EA = 1 / (1.0 + math.pow(10.0, (opponentELO - curELO) / 400.0))

                    # calculate ELO change vs this one opponent, add it to our change bucket
                    # I currently round at this point, this keeps rounding changes symetrical between EA and EB, but changes K more than it should
                    self.players[i].eloChange += round(K * (S - EA))

                    # add accumulated change to initial ELO for final ELO

            self.players[i].eloPost = self.players[i].eloPre + self.players[i].eloChange

